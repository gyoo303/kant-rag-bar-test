"""TKT-BE-M3-05: 평가 실행 `eval run` (AC-12-1·2·3, AC-13-1·2·3·4, R-1, 이어 하기).

대역 AnswerService, 기록은 임시 폴더의 실제 파일 저장소(DB·API 없음).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lawqa.answering.application.answer_service import AnswerEnvelope
from lawqa.answering.domain.models import (
    Answer,
    Citation,
    ErrorCode,
    OptionJudgment,
    Outcome,
    Verdict,
)
from lawqa.evaluation.application.run_service import EvalRunService
from lawqa.evaluation.domain.errors import (
    FROZEN_MISMATCH,
    TEST_SPLIT_IN_DEV,
    InvalidEvalDataError,
    RuleViolationError,
)
from lawqa.evaluation.domain.models import FreezeRecord, FreezeStage, Split
from lawqa.evaluation.domain.run import RunKind, RunStatus
from lawqa.evaluation.infrastructure.files import FreezeFile, JsonEvalSetRepository, RunStore
from lawqa.retrieval.domain.models import Candidate, OptionQuery, OptionResult, RetrievalResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eval"
FROZEN = FreezeRecord(
    stage=FreezeStage.FINAL,
    success_criteria_sha="crit",
    evalset_sha="evalset",
    config_sha={"A": "a", "B": "b", "C": "c", "C+R": "cr"},
    prompt_sha="prompt",
    index_version="idx-1",
)
VERSIONS = {
    "corpus": "corpus-1",
    "index": "idx-1",
    "config_sha": "c",
    "prompt_sha": "prompt",
    "gen_model": "gpt-6-luna",
    "embedding_model": "text-embedding-3-small/1536",
    "reranker_model": "BAAI/bge-reranker-v2-m3",
}


class StepClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 27, 10, 0, 0).astimezone()

    def now(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def _retrieval(config: str) -> RetrievalResult:
    return RetrievalResult(
        config_name=config,  # type: ignore[arg-type]
        options=tuple(
            OptionResult(
                OptionQuery(n, f"q{n}"),
                (
                    Candidate(
                        f"c{n}",
                        f"d{n}",
                        f"loc{n}",
                        "본문",
                        bm25_rank=1,
                        fused_rank=1,
                        rerank_score=0.5,
                        final_rank=1,
                    ),
                ),
            )
            for n in range(1, 6)
        ),
    )


def _envelope(config: str, outcome: Outcome = Outcome.ANSWERED) -> AnswerEnvelope:
    if outcome is Outcome.ANSWERED:
        answer = Answer(
            outcome,
            2,
            tuple(
                OptionJudgment(n, Verdict.CORRECT, "r", (Citation("c2", "loc2"),) if n == 2 else ())
                for n in range(1, 6)
            ),
            None,
            "정답: 2번",
        )
    elif outcome is Outcome.RETRIEVAL_ERROR:
        answer = Answer.error(outcome, ErrorCode.RETRIEVAL_FAILED, "검색 오류")
    else:
        answer = Answer.error(outcome, ErrorCode.MODEL_TIMEOUT, "답변 생성 오류")
    retrieval = None if outcome is Outcome.RETRIEVAL_ERROR else _retrieval(config)
    context = tuple(o.candidates[0] for o in retrieval.options) if retrieval else ()
    return AnswerEnvelope(
        answer=answer,
        config_name=config,
        retrieval=retrieval,
        context=context,
        prompt_sha="prompt",
        raw_output='{"answer": 2}',
        latency_ms=1200,
        queries=tuple(o.query for o in retrieval.options) if retrieval else (),
        retrieval_ms=400,
        generation_ms=800,
    )


class StubAnswerer:
    """질문 순서대로 결과 종류를 정한다. `stop_after`건 뒤에는 중단(KeyboardInterrupt)."""

    def __init__(self, outcomes: dict[int, Outcome] | None = None, stop_after: int | None = None):
        self.outcomes = outcomes or {}
        self.stop_after = stop_after
        self.calls: list[str] = []

    def answer(self, item_input, config_name):
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise KeyboardInterrupt
        self.calls.append(item_input["stem"])
        outcome = self.outcomes.get(len(self.calls), Outcome.ANSWERED)
        return _envelope(config_name, outcome)


@pytest.fixture
def env(tmp_path):
    state = {"answerer": StubAnswerer(), "built": 0, "versions": dict(VERSIONS)}
    freeze = FreezeFile(tmp_path / "FREEZE.json")
    store = RunStore(tmp_path / "results")

    def answerer():
        state["built"] += 1
        return state["answerer"]

    service = EvalRunService(
        evalsets=JsonEvalSetRepository(FIXTURES),
        freeze_store=freeze,
        current_freeze=lambda: state.get("current", FROZEN),
        store=store,
        versions_for=lambda name: state["versions"],
        answerer=answerer,
        clock=StepClock(),
    )
    return service, store, freeze, state, tmp_path


def _records(store: RunStore, run_id: str):
    return store.load(run_id)[1]


# ── dev 워밍업: 고정 없이 실행, 기록 필드 (AC-13-2) ──
def test_dev_warmup_records_every_question_with_all_fields(env):
    service, store, _, state, tmp = env
    summary = service.run(Split.DEV, "C", RunKind.WARMUP)

    records = _records(store, summary.plan.run_id)
    assert len(records) == 10 and summary.recorded == 10
    r = records[0]
    assert r.run_id.endswith("-C-warmup") and r.question_id == "DEV-01"
    assert r.kind is RunKind.WARMUP and r.status is RunStatus.OK and r.outcome == "ANSWERED"
    assert dict(r.versions) == VERSIONS
    assert r.latency_ms == {
        "total": 1200,
        "rewrite": None,
        "retrieval": 400,
        "rerank": None,
        "generation": 800,
    }
    assert r.question_list == ("c1", "c2", "c3", "c4", "c5")
    line = json.loads(
        (tmp / "results" / r.run_id / "records.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    for key in (
        "queries",
        "candidates",
        "context_chunk_ids",
        "context_chars",
        "raw_output",
        "answer",
        "citations",
    ):
        assert line[key] not in (None, "", [], {}), key
    assert line["candidates"]["3"][0]["rerank_score"] == 0.5  # 재정렬 점수·전후 순위
    assert line["citations"] == [{"chunk_id": "c2", "location": "loc2"}]


# ── 거부 (AC-12-2·3) ──
def test_test_split_warmup_is_refused_without_files_or_models(env):
    service, store, _, state, tmp = env
    with pytest.raises(RuleViolationError) as exc:
        service.run(Split.TEST, "C", RunKind.WARMUP)
    assert exc.value.code == TEST_SPLIT_IN_DEV
    assert state["built"] == 0 and not (tmp / "results").exists()


def test_main_without_final_freeze_is_refused(env):
    service, *_ = env
    with pytest.raises(RuleViolationError) as exc:
        service.run(Split.TEST, "C", RunKind.MAIN)
    assert exc.value.code == FROZEN_MISMATCH


def test_main_refused_when_settings_changed_after_freeze(env):
    service, _, freeze, state, _ = env
    freeze.save(FROZEN)
    state["current"] = replace(FROZEN, config_sha={**FROZEN.config_sha, "C": "CHANGED"})
    with pytest.raises(RuleViolationError) as exc:
        service.run(Split.TEST, "C", RunKind.MAIN)
    assert exc.value.code == FROZEN_MISMATCH and "config_sha" in str(exc.value)
    # 같은 변경으로도 추가 실험은 실행할 수 있다(REJ-08)
    assert service.run(Split.TEST, "C", RunKind.EXTRA, only=["TEST-01"]).recorded == 1


# ── 본 평가 (AC-13-1·4, AC-12-1) ──
def test_main_runs_records_twenty_per_config_with_same_versions(env):
    service, store, freeze, _, _ = env
    freeze.save(FROZEN)
    run_ids = [service.run(Split.TEST, c, RunKind.MAIN).plan.run_id for c in ("A", "B", "C", "C+R")]

    all_records = [r for rid in run_ids for r in _records(store, rid)]
    assert len(all_records) == 80
    assert {r.config_name for r in all_records} == {"A", "B", "C", "C+R"}
    assert all(r.counts_in_main_metrics for r in all_records)
    # AC-13-4·12-1: 모델·프롬프트·색인 버전이 모든 기록에서 같고 고정 값과 같다
    assert {
        (r.versions["gen_model"], r.versions["prompt_sha"], r.versions["index"])
        for r in all_records
    } == {("gpt-6-luna", FROZEN.prompt_sha, FROZEN.index_version)}


# ── 오류·재시도 (AC-13-3, R-1) ──
def test_retry_records_failed_questions_separately_and_keeps_originals(env):
    service, store, freeze, state, tmp = env
    freeze.save(FROZEN)
    state["answerer"] = StubAnswerer({2: Outcome.RETRIEVAL_ERROR, 5: Outcome.MODEL_ERROR})
    main_id = service.run(Split.TEST, "C", RunKind.MAIN).plan.run_id
    original_text = (tmp / "results" / main_id / "records.jsonl").read_text(encoding="utf-8")

    main = _records(store, main_id)
    assert [(r.question_id, r.status) for r in main if r.status is not RunStatus.OK] == [
        ("TEST-02", RunStatus.ERROR),
        ("TEST-05", RunStatus.TIMEOUT),
    ]
    assert all(r.error_code for r in main if r.status is not RunStatus.OK)

    state["answerer"] = StubAnswerer()
    retry = service.run(Split.TEST, "C", RunKind.RETRY, retry_of=main_id)
    retry_records = _records(store, retry.plan.run_id)
    assert [r.question_id for r in retry_records] == ["TEST-02", "TEST-05"]
    assert all(
        r.kind is RunKind.RETRY and r.retry_of == main_id and r.attempt == 2 for r in retry_records
    )
    assert not any(r.counts_in_main_metrics for r in retry_records)
    # 원 기록은 그대로
    assert (tmp / "results" / main_id / "records.jsonl").read_text(
        encoding="utf-8"
    ) == original_text


def test_retry_must_point_to_main_run_of_same_config(env):
    service, store, freeze, _, _ = env
    freeze.save(FROZEN)
    main_id = service.run(Split.TEST, "C", RunKind.MAIN, only=["TEST-01"]).plan.run_id
    with pytest.raises(RuleViolationError):
        service.run(Split.TEST, "B", RunKind.RETRY, retry_of=main_id)
    with pytest.raises(InvalidEvalDataError):
        service.run(Split.TEST, "C", RunKind.RETRY, retry_of="20261127-000000-C-main")


# ── 중단 후 이어 하기 ──
def test_interrupted_run_resumes_without_duplicates(env):
    service, store, _, state, _ = env
    state["answerer"] = StubAnswerer(stop_after=3)
    with pytest.raises(KeyboardInterrupt):
        service.run(Split.DEV, "B", RunKind.WARMUP)
    run_id = next(p.name for p in store.run_dir("x").parent.iterdir())
    assert len(_records(store, run_id)) == 3  # 멈추기 전 기록은 남음

    state["answerer"] = StubAnswerer()
    summary = service.run(Split.DEV, "B", RunKind.WARMUP, resume_run_id=run_id)
    assert summary.plan.resumed and summary.recorded == 7
    ids = [r.question_id for r in _records(store, run_id)]
    assert len(ids) == len(set(ids)) == 10


def test_resume_refused_when_versions_changed(env):
    service, store, _, state, _ = env
    run_id = service.run(Split.DEV, "B", RunKind.WARMUP, only=["DEV-01"]).plan.run_id
    state["versions"] = {**VERSIONS, "prompt_sha": "new"}
    with pytest.raises(RuleViolationError):
        service.run(Split.DEV, "B", RunKind.WARMUP, resume_run_id=run_id)


def test_resume_requires_matching_arguments(env):
    service, *_ = env
    run_id = service.run(Split.DEV, "B", RunKind.WARMUP, only=["DEV-01"]).plan.run_id
    with pytest.raises(InvalidEvalDataError):
        service.run(Split.DEV, "C", RunKind.WARMUP, resume_run_id=run_id)


# ── --only, --dry-run ──
def test_only_selects_questions_and_rejects_unknown_ids(env):
    service, *_ = env
    assert service.plan(Split.DEV, "A", RunKind.WARMUP, only=["DEV-03", "DEV-01"]).question_ids == (
        "DEV-01",
        "DEV-03",
    )
    with pytest.raises(InvalidEvalDataError):
        service.plan(Split.DEV, "A", RunKind.WARMUP, only=["TEST-01"])


def test_dry_run_plan_creates_nothing(env):
    service, _, freeze, state, tmp = env
    freeze.save(FROZEN)
    plan = service.plan(Split.TEST, "C", RunKind.MAIN, only=["TEST-01"])
    assert plan.run_id.endswith("-C-main") and plan.question_ids == ("TEST-01",)
    assert state["built"] == 0 and not (tmp / "results").exists()

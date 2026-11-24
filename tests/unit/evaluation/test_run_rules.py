"""TKT-BE-M1-03: 실행 허용 규칙·실행 기록·Hit@5 (INV-05·06·07·11, AC-12-2·3, REQ-071)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from lawqa.evaluation.domain.errors import (
    FROZEN_MISMATCH,
    INVALID_RUN_KIND,
    TEST_SPLIT_IN_DEV,
    InvalidEvalDataError,
    RuleViolationError,
)
from lawqa.evaluation.domain.metrics import Grade, hit_at_5, hit_at_5_total
from lawqa.evaluation.domain.models import EvalSet, FreezeRecord, FreezeStage, Split
from lawqa.evaluation.domain.run import Run, RunKind, RunRecord, RunStatus

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eval"
VERSIONS = {
    "corpus": "corpus",
    "index": "idx-1",
    "config_sha": "c",
    "prompt_sha": "p",
    "gen_model": "gpt-6-luna",
    "embedding_model": "text-embedding-3-small",
    "reranker_model": "BAAI/bge-reranker-v2-m3",
}
LATENCY = {"total": 100, "rewrite": None, "retrieval": 40, "rerank": 10, "generation": 50}
FINAL = FreezeRecord(
    stage=FreezeStage.FINAL,
    success_criteria_sha="crit",
    evalset_sha="evalset",
    config_sha={"C": "c"},
    prompt_sha="prompt",
    index_version="idx-1",
)


def _record(**changes) -> RunRecord:
    record = RunRecord(
        run_id="20261127-100000-C-main",
        kind=RunKind.MAIN,
        split=Split.TEST,
        config_name="C",
        versions=VERSIONS,
        question_id="TEST-01",
        attempt=1,
        started_at="2026-11-27T10:00:01+09:00",
        latency_ms=LATENCY,
        status=RunStatus.OK,
        outcome="ANSWERED",
        question_list=("x", "y", "law:민법:101-0#ARTICLE#1", "z"),
    )
    return replace(record, **changes)


@pytest.mark.parametrize(
    ("kind", "split", "code"),
    [
        (RunKind.WARMUP, Split.TEST, TEST_SPLIT_IN_DEV),
        (RunKind.MAIN, Split.DEV, INVALID_RUN_KIND),
        (RunKind.RETRY, Split.DEV, INVALID_RUN_KIND),
    ],
)
def test_ac_12_2_wrong_split_kind_rejected(kind: RunKind, split: Split, code: str) -> None:
    with pytest.raises(RuleViolationError) as exc_info:
        Run.check_allowed(kind, split, FINAL, FINAL, retry_of="r")

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("kind", "split"),
    [(RunKind.WARMUP, Split.DEV), (RunKind.EXTRA, Split.DEV), (RunKind.EXTRA, Split.TEST)],
)
def test_dev_tuning_and_extra_runs_need_no_freeze(kind: RunKind, split: Split) -> None:
    Run.check_allowed(kind, split, None, FINAL)


def test_main_run_requires_final_freeze() -> None:
    criteria_only = FreezeRecord(stage=FreezeStage.CRITERIA, success_criteria_sha="crit")

    for freeze in (None, criteria_only):
        with pytest.raises(RuleViolationError) as exc_info:
            Run.check_allowed(RunKind.MAIN, Split.TEST, freeze, FINAL)
        assert exc_info.value.code == FROZEN_MISMATCH


def test_ac_12_3_main_run_rejected_when_settings_changed_after_freeze() -> None:
    changed = replace(FINAL, prompt_sha="prompt-v2")

    with pytest.raises(RuleViolationError) as exc_info:
        Run.check_allowed(RunKind.MAIN, Split.TEST, FINAL, changed)

    assert exc_info.value.code == FROZEN_MISMATCH


def test_main_run_allowed_when_frozen_values_match() -> None:
    Run.check_allowed(RunKind.MAIN, Split.TEST, FINAL, FINAL)


def test_retry_run_requires_retry_of() -> None:
    with pytest.raises(RuleViolationError) as exc_info:
        Run.check_allowed(RunKind.RETRY, Split.TEST, FINAL, FINAL)

    assert exc_info.value.code == INVALID_RUN_KIND
    Run.check_allowed(RunKind.RETRY, Split.TEST, FINAL, FINAL, retry_of="20261127-100000-C-main")


def test_run_id_format_and_make_id() -> None:
    started = datetime(2026, 11, 27, 10, 0, 0)
    run_id = Run.make_id(started, "C+R", RunKind.MAIN)

    run = Run(run_id, RunKind.MAIN, Split.TEST, "C+R", VERSIONS, started)

    assert run.run_id == "20261127-100000-C+R-main"
    with pytest.raises(InvalidEvalDataError, match="run_id"):
        Run("bad-id", RunKind.MAIN, Split.TEST, "C", VERSIONS, started)
    with pytest.raises(InvalidEvalDataError, match="구성·종류"):
        Run(run_id, RunKind.MAIN, Split.TEST, "C", VERSIONS, started)


def test_run_record_requires_all_versions_inv_11() -> None:
    versions = {k: v for k, v in VERSIONS.items() if k != "prompt_sha"}

    with pytest.raises(InvalidEvalDataError, match="INV-11"):
        _record(versions=versions)


def test_run_record_error_requires_error_code_and_retry_rules() -> None:
    with pytest.raises(InvalidEvalDataError, match="error_code"):
        _record(status=RunStatus.ERROR)
    with pytest.raises(InvalidEvalDataError, match="retry_of"):
        _record(kind=RunKind.RETRY)
    retry = _record(kind=RunKind.RETRY, retry_of="20261127-100000-C-main")
    assert not retry.counts_in_main_metrics


def _test_set() -> EvalSet:
    return EvalSet.from_dict(json.loads((FIXTURES / "test.json").read_text(encoding="utf-8")))


def test_hit_at_5_counts_allowed_chunk_in_top_five() -> None:
    question = _test_set().get("TEST-01")  # 허용 근거 law:민법:101-0#ARTICLE#1

    assert hit_at_5(_record(), question) == 1
    late = ("a", "b", "c", "d", "e", "law:민법:101-0#ARTICLE#1")
    assert hit_at_5(_record(question_list=late), question) == 0


def test_hit_at_5_retrieval_failure_is_zero_and_short_list_is_ok() -> None:
    question = _test_set().get("TEST-01")

    failed = _record(status=RunStatus.ERROR, error_code="RETRIEVAL_FAILED")
    assert hit_at_5(failed, question) == 0
    assert hit_at_5(_record(question_list=("law:민법:101-0#ARTICLE#1",)), question) == 1


def test_hit_at_5_total_uses_main_answerable_records_only() -> None:
    evalset = _test_set()
    questions = {q.question_id: q for q in evalset.questions}
    records = [
        _record(question_id=q.question_id, question_list=(f"law:민법:{100 + i}-0#ARTICLE#1",))
        for i, q in enumerate(evalset.questions, start=1)
    ]
    records.append(_record(kind=RunKind.RETRY, retry_of="20261127-100000-C-main"))

    hits, denominator = hit_at_5_total(records, questions)

    assert (hits, denominator) == (17, 17)


def test_grade_values_and_llm_prompt_sha() -> None:
    Grade("r", "TEST-01", "HUMAN", 1, 1, 0, None)
    with pytest.raises(InvalidEvalDataError, match="0·1"):
        Grade("r", "TEST-01", "HUMAN", 2, 1, 0, None)
    with pytest.raises(InvalidEvalDataError, match="judge_prompt_sha"):
        Grade("r", "TEST-01", "LLM", 1, 1, 1, None)

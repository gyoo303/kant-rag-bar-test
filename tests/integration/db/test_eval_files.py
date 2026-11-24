"""TKT-DB-M1-02: 평가 파일 저장소 (03-db-schema §5·§7, ADR-014, INV-07). DB 없이 tmp_path 사용."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from lawqa.evaluation.domain.errors import InvalidEvalDataError
from lawqa.evaluation.domain.metrics import Grade
from lawqa.evaluation.domain.models import FreezeRecord, FreezeStage, Split
from lawqa.evaluation.domain.run import Run, RunKind, RunRecord, RunStatus
from lawqa.evaluation.infrastructure.files import (
    FreezeFile,
    JsonEvalSetRepository,
    RunStore,
    SuccessCriteriaFile,
)

FIXTURE_EVAL = Path(__file__).resolve().parents[2] / "fixtures" / "eval"
VERSIONS = {
    "corpus": "corpus",
    "index": "idx-1",
    "config_sha": "c",
    "prompt_sha": "p",
    "gen_model": "gpt-6-luna",
    "embedding_model": "text-embedding-3-small",
    "reranker_model": "BAAI/bge-reranker-v2-m3",
}
STARTED = datetime(2026, 11, 27, 10, 0, 0).astimezone()
RUN = Run(
    run_id="20261127-100000-C-main",
    kind=RunKind.MAIN,
    split=Split.TEST,
    config_name="C",
    versions=VERSIONS,
    started_at=STARTED,
)


def _record(question_id: str, **changes) -> RunRecord:
    record = RunRecord(
        run_id=RUN.run_id,
        kind=RunKind.MAIN,
        split=Split.TEST,
        config_name="C",
        versions=VERSIONS,
        question_id=question_id,
        attempt=1,
        started_at="2026-11-27T10:00:01+09:00",
        latency_ms={
            "total": 900,
            "rewrite": None,
            "retrieval": 300,
            "rerank": 100,
            "generation": 500,
        },
        status=RunStatus.OK,
        outcome="ANSWERED",
        question_list=("law:민법:245-0#ARTICLE#1", "prec:1#HOLDING#1"),
        details={
            "queries": [
                {"option_no": 1, "original": "보기 1", "rewritten": None, "fallback": False}
            ],
            "raw_output": '{"answer": 3}',
        },
    )
    return replace(record, **changes)


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    target = tmp_path / "eval"
    shutil.copytree(FIXTURE_EVAL, target)
    return target


def test_eval_set_repository_loads_dev_and_test(eval_dir: Path) -> None:
    repo = JsonEvalSetRepository(eval_dir)

    assert len(repo.load(Split.DEV).questions) == 10
    assert len(repo.load(Split.TEST).questions) == 20


def test_eval_set_repository_missing_or_broken_file_is_input_error(eval_dir: Path) -> None:
    (eval_dir / "dev.json").unlink()
    (eval_dir / "test.json").write_text("{not json", encoding="utf-8")
    repo = JsonEvalSetRepository(eval_dir)

    with pytest.raises(InvalidEvalDataError, match="파일이 없습니다"):
        repo.load(Split.DEV)
    with pytest.raises(InvalidEvalDataError, match="JSON 형식 오류"):
        repo.load(Split.TEST)


def test_success_criteria_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "success_criteria.json"
    path.write_text(
        json.dumps(
            {
                "priority": ["quality", "latency", "cost"],
                "targets": {
                    "hit_at_5": 14,
                    "answer_correct": 12,
                    "citation_valid": 13,
                    "abstain_correct": 3,
                    "latency_median_s": 30,
                    "call_success_rate": 0.95,
                },
            }
        ),
        encoding="utf-8",
    )

    assert SuccessCriteriaFile(path).load().targets["hit_at_5"] == 14


def test_freeze_file_absent_then_round_trip(tmp_path: Path) -> None:
    store = FreezeFile(tmp_path / "FREEZE.json")
    record = FreezeRecord(stage=FreezeStage.CRITERIA, success_criteria_sha="crit")

    assert store.load() is None
    store.save(record)
    assert store.load() == record
    assert not (tmp_path / "FREEZE.json.tmp").exists()


def test_run_store_create_append_load_round_trip(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)
    first = _record("TEST-01")
    failed = _record(
        "TEST-02", status=RunStatus.ERROR, outcome="MODEL_ERROR", error_code="MODEL_TIMEOUT"
    )

    store.append(first)
    store.append(failed)
    run, records = store.load(RUN.run_id)

    assert run == RUN
    assert records == [first, failed]
    assert records[0].details["raw_output"] == '{"answer": 3}'


def test_run_store_append_writes_one_json_line_per_record(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)
    store.append(_record("TEST-01"))
    store.append(_record("TEST-02"))

    raw = (tmp_path / "results" / RUN.run_id / "records.jsonl").read_bytes()
    lines = raw.decode("utf-8").split("\n")

    assert raw.endswith(b"\n") and b"\r\n" not in raw
    assert len(lines) == 3 and lines[2] == ""
    assert [json.loads(line)["question_id"] for line in lines[:2]] == ["TEST-01", "TEST-02"]
    assert json.loads(lines[0])["queries"][0]["original"] == "보기 1"


def test_run_store_reopen_after_interruption_keeps_existing_lines(tmp_path: Path) -> None:
    results = tmp_path / "results"
    first_session = RunStore(results)
    first_session.create(RUN)
    first_session.append(_record("TEST-01"))
    del first_session  # 실행이 여기서 멈췄다고 보고 새 저장소로 이어서 씀(--resume)

    second_session = RunStore(results)
    second_session.append(_record("TEST-02"))
    _, records = second_session.load(RUN.run_id)

    assert [r.question_id for r in records] == ["TEST-01", "TEST-02"]


def test_run_store_create_twice_does_not_overwrite(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)
    store.append(_record("TEST-01"))
    before = (tmp_path / "results" / RUN.run_id / "run.json").read_bytes()

    with pytest.raises(FileExistsError, match="--resume"):
        store.create(RUN)

    assert (tmp_path / "results" / RUN.run_id / "run.json").read_bytes() == before
    assert len(store.load(RUN.run_id)[1]) == 1


def test_run_store_append_requires_created_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="create"):
        RunStore(tmp_path / "results").append(_record("TEST-01"))


def test_run_store_truncated_last_line_reported_not_repaired(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)
    store.append(_record("TEST-01"))
    records_path = tmp_path / "results" / RUN.run_id / "records.jsonl"
    with records_path.open("a", encoding="utf-8") as handle:
        handle.write('{"run_id": "20261127-100000-C-main", "question')
    before = records_path.read_bytes()

    with pytest.raises(InvalidEvalDataError, match="records.jsonl:2.*마지막 줄이 잘림"):
        store.load(RUN.run_id)

    assert records_path.read_bytes() == before


def test_run_store_rejects_details_overlapping_fixed_fields(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)

    with pytest.raises(InvalidEvalDataError, match="고정 필드"):
        store.append(_record("TEST-01", details={"status": "OK"}))


def test_run_store_grades_append_and_load(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "results")
    store.create(RUN)
    llm = Grade(RUN.run_id, "TEST-01", "LLM", 1, 1, 1, None, "근거 일치", "judge-sha")
    human = Grade(RUN.run_id, "TEST-01", "HUMAN", 1, 0, 1, None, "핵심 사실 하나 틀림")

    store.append_grade(llm)
    store.append_grade(human)

    assert store.load_grades(RUN.run_id) == [llm, human]

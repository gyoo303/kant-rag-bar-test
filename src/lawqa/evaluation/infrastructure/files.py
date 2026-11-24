"""평가 파일 저장소 (ADR-006, ADR-014, 03-db-schema §5·§7).

- `eval/`: 평가셋(`dev.json`, `test.json`), 성공 기준(`success_criteria.json`),
  고정 기록(`FREEZE.json`)
- `results/<run_id>/`: `run.json`(실행 머리 정보), `records.jsonl`(문항 1건 = 한 줄), `grades.jsonl`
- 기록 파일은 append 전용이다. 한 줄을 쓰자마자 flush·fsync 해서 실행이 멈춰도 쓴 줄은 남고,
  기존 줄은 고치거나 지우지 않는다(INV-07, 금지 패턴 13).

이 모듈만 `eval/`을 읽는다(ADR-001, INV-04). dict ↔ 도메인 검증은 도메인의 `from_dict`가 한다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from lawqa.evaluation.domain.errors import InvalidEvalDataError
from lawqa.evaluation.domain.metrics import Grade
from lawqa.evaluation.domain.models import EvalSet, FreezeRecord, Split, SuccessCriteria
from lawqa.evaluation.domain.run import Run, RunKind, RunRecord, RunStatus

RUN_FILE = "run.json"
RECORDS_FILE = "records.jsonl"
GRADES_FILE = "grades.jsonl"

# RunRecord 의 고정 필드(03-db-schema §5). 나머지 키는 `details`로 주고받는다.
_RECORD_FIELDS = (
    "run_id",
    "kind",
    "split",
    "config_name",
    "versions",
    "question_id",
    "attempt",
    "retry_of",
    "started_at",
    "latency_ms",
    "status",
    "outcome",
    "error_code",
    "question_list",
)


class JsonEvalSetRepository:
    """`<eval_dir>/<split>.json`을 읽어 `EvalSet`으로 돌려준다."""

    def __init__(self, eval_dir: Path) -> None:
        self._eval_dir = eval_dir

    def load(self, split: Split) -> EvalSet:
        return EvalSet.from_dict(_read_json(self._eval_dir / f"{split.value}.json"))


class SuccessCriteriaFile:
    """`<eval_dir>/success_criteria.json` (사람이 작성, US-02)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> SuccessCriteria:
        return SuccessCriteria.from_dict(_read_json(self._path))


class FreezeFile:
    """`<eval_dir>/FREEZE.json`. 없으면 `load()`가 `None`.

    고정 규칙(재고정 금지)은 응용 서비스(`FreezeService`)가 검사한다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> FreezeRecord | None:
        if not self._path.exists():
            return None
        return FreezeRecord.from_dict(_read_json(self._path))

    def save(self, record: FreezeRecord) -> None:
        _write_json_atomic(self._path, record.to_dict())


class RunStore:
    """`<results_dir>/<run_id>/` 실행 기록. 줄 단위 append 전용."""

    def __init__(self, results_dir: Path) -> None:
        self._results_dir = results_dir

    def run_dir(self, run_id: str) -> Path:
        return self._results_dir / run_id

    def exists(self, run_id: str) -> bool:
        return (self.run_dir(run_id) / RUN_FILE).exists()

    def create(self, run: Run) -> None:
        """새 실행 폴더와 `run.json`을 만든다. 이미 있으면 `FileExistsError`(덮어쓰지 않음)."""
        run_dir = self.run_dir(run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / RUN_FILE
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(_dumps(_run_to_dict(run), indent=2))
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise FileExistsError(
                f"실행 {run.run_id}가 이미 있습니다. 이어서 하려면 --resume을 쓰세요."
            ) from exc

    def append(self, record: RunRecord) -> None:
        """문항 1건 기록을 한 줄 JSON으로 덧붙이고 바로 디스크에 쓴다."""
        self._append_line(record.run_id, RECORDS_FILE, _record_to_dict(record))

    def append_grade(self, grade: Grade) -> None:
        self._append_line(grade.run_id, GRADES_FILE, _grade_to_dict(grade))

    def load(self, run_id: str) -> tuple[Run, list[RunRecord]]:
        run_dir = self.run_dir(run_id)
        run = _run_from_dict(_read_json(run_dir / RUN_FILE))
        records = [_record_from_dict(d) for d in _read_jsonl(run_dir / RECORDS_FILE)]
        return run, records

    def load_grades(self, run_id: str) -> list[Grade]:
        return [_grade_from_dict(d) for d in _read_jsonl(self.run_dir(run_id) / GRADES_FILE)]

    def _append_line(self, run_id: str, file_name: str, data: Mapping[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        if not (run_dir / RUN_FILE).exists():
            raise FileNotFoundError(f"실행 {run_id}의 {RUN_FILE}이 없습니다. create를 먼저 하세요.")
        line = _dumps(data) + "\n"
        with (run_dir / file_name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def _dumps(data: Any, indent: int | None = None) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InvalidEvalDataError(f"파일이 없습니다: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidEvalDataError(f"JSON 형식 오류: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidEvalDataError(f"JSON 최상위는 객체여야 합니다: {path}")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """줄 단위 JSON을 읽는다. 깨진 줄이 있으면 파일·줄 번호와 함께 오류를 낸다(고치지 않음)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            truncated = line_no == len(lines) and not text.endswith("\n")
            hint = " (마지막 줄이 잘림: 실행이 쓰는 중에 멈춘 것으로 보입니다)" if truncated else ""
            raise InvalidEvalDataError(f"{path}:{line_no} JSON 형식 오류{hint}: {exc}") from exc
    return rows


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _run_to_dict(run: Run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "kind": run.kind.value,
        "split": run.split.value,
        "config_name": run.config_name,
        "versions": dict(run.versions),
        "started_at": run.started_at.isoformat(timespec="seconds"),
        "retry_of": run.retry_of,
    }


def _run_from_dict(data: Mapping[str, Any]) -> Run:
    try:
        return Run(
            run_id=data["run_id"],
            kind=RunKind(data["kind"]),
            split=Split(data["split"]),
            config_name=data["config_name"],
            versions=dict(data["versions"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            retry_of=data.get("retry_of"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidEvalDataError):
            raise
        raise InvalidEvalDataError(f"run.json 형식 오류 ({exc})") from exc


def _record_to_dict(record: RunRecord) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": record.run_id,
        "kind": record.kind.value,
        "split": record.split.value,
        "config_name": record.config_name,
        "versions": dict(record.versions),
        "question_id": record.question_id,
        "attempt": record.attempt,
        "retry_of": record.retry_of,
        "started_at": record.started_at,
        "latency_ms": dict(record.latency_ms),
        "status": record.status.value,
        "outcome": record.outcome,
        "error_code": record.error_code,
        "question_list": list(record.question_list),
    }
    overlap = set(data) & set(record.details)
    if overlap:
        raise InvalidEvalDataError(f"details가 고정 필드와 겹칩니다: {sorted(overlap)}")
    data.update(record.details)
    return data


def _record_from_dict(data: Mapping[str, Any]) -> RunRecord:
    try:
        return RunRecord(
            run_id=data["run_id"],
            kind=RunKind(data["kind"]),
            split=Split(data["split"]),
            config_name=data["config_name"],
            versions=dict(data["versions"]),
            question_id=data["question_id"],
            attempt=int(data["attempt"]),
            started_at=data["started_at"],
            latency_ms=dict(data["latency_ms"]),
            status=RunStatus(data["status"]),
            outcome=data["outcome"],
            question_list=tuple(data.get("question_list") or ()),
            error_code=data.get("error_code"),
            retry_of=data.get("retry_of"),
            details={k: v for k, v in data.items() if k not in _RECORD_FIELDS},
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidEvalDataError):
            raise
        raise InvalidEvalDataError(f"실행 기록 형식 오류 ({exc})") from exc


def _grade_to_dict(grade: Grade) -> dict[str, Any]:
    return {
        "run_id": grade.run_id,
        "question_id": grade.question_id,
        "grader": grade.grader,
        "hit_at_5": grade.hit_at_5,
        "answer_correct": grade.answer_correct,
        "citation_valid": grade.citation_valid,
        "abstain_correct": grade.abstain_correct,
        "rationale": grade.rationale,
        "judge_prompt_sha": grade.judge_prompt_sha,
    }


def _grade_from_dict(data: Mapping[str, Any]) -> Grade:
    try:
        return Grade(
            run_id=data["run_id"],
            question_id=data["question_id"],
            grader=data["grader"],
            hit_at_5=data.get("hit_at_5"),
            answer_correct=data.get("answer_correct"),
            citation_valid=data.get("citation_valid"),
            abstain_correct=data.get("abstain_correct"),
            rationale=data.get("rationale") or "",
            judge_prompt_sha=data.get("judge_prompt_sha"),
        )
    except KeyError as exc:
        raise InvalidEvalDataError(f"채점 기록 형식 오류 (필드 없음: {exc})") from exc

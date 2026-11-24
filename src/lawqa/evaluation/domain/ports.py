"""evaluation 저장소 계약 (03-db-schema §7). 구현은 `evaluation.infrastructure.files`(DB 티켓)."""

from __future__ import annotations

from typing import Protocol

from lawqa.evaluation.domain.metrics import Grade
from lawqa.evaluation.domain.models import EvalSet, FreezeRecord, Split, SuccessCriteria
from lawqa.evaluation.domain.run import Run, RunRecord


class EvalSetRepository(Protocol):
    def load(self, split: Split) -> EvalSet: ...


class SuccessCriteriaStore(Protocol):
    def load(self) -> SuccessCriteria: ...


class FreezeStore(Protocol):
    def load(self) -> FreezeRecord | None: ...
    def save(self, record: FreezeRecord) -> None: ...


class RunStore(Protocol):
    def create(self, run: Run) -> None: ...
    def append(self, record: RunRecord) -> None: ...
    def load(self, run_id: str) -> tuple[Run, list[RunRecord]]: ...
    def append_grade(self, grade: Grade) -> None: ...

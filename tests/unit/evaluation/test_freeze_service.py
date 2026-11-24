"""TKT-BE-M1-04: 고정 서비스 (US-02·12, AC-02-1·2, SEQ-06, §9.3). 저장소·git·시각은 가짜."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lawqa.evaluation.application.freeze_service import FreezeService
from lawqa.evaluation.domain.errors import FROZEN_MISMATCH, RuleViolationError
from lawqa.evaluation.domain.models import (
    EvalSet,
    FreezeRecord,
    FreezeStage,
    Split,
    SuccessCriteria,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eval"
TARGETS = {
    "hit_at_5": 14,
    "answer_correct": 12,
    "citation_valid": 13,
    "abstain_correct": 3,
    "latency_median_s": 30,
    "call_success_rate": 0.95,
}
T0 = datetime(2026, 11, 24, 18, 0, 0).astimezone()


class Clock:
    def __init__(self) -> None:
        self.value = T0

    def now(self) -> datetime:
        return self.value


class Criteria:
    def __init__(self) -> None:
        self.value = SuccessCriteria(priority=("quality", "latency", "cost"), targets=TARGETS)

    def load(self) -> SuccessCriteria:
        return self.value


class EvalSets:
    def load(self, split: Split) -> EvalSet:
        data = json.loads((FIXTURES / f"{split.value}.json").read_text(encoding="utf-8"))
        return EvalSet.from_dict(data)


class Freezes:
    def __init__(self) -> None:
        self.saved: list[FreezeRecord] = []

    def load(self) -> FreezeRecord | None:
        return self.saved[-1] if self.saved else None

    def save(self, record: FreezeRecord) -> None:
        self.saved.append(record)


class Git:
    def __init__(self, dirty: bool = False) -> None:
        self.dirty = dirty

    def head(self) -> str:
        return "abc123"

    def has_uncommitted_changes(self) -> bool:
        return self.dirty


class Env:
    def __init__(self, dirty: bool = False) -> None:
        self.criteria = Criteria()
        self.freezes = Freezes()
        self.git = Git(dirty)
        self.clock = Clock()
        self.prompt = "prompt-v1"
        self.service = FreezeService(
            criteria_store=self.criteria,
            evalset_repo=EvalSets(),
            freeze_store=self.freezes,
            config_shas=lambda: {"A": "a", "B": "b", "C": "c", "C+R": "cr"},
            prompt_sha=lambda: self.prompt,
            index_version=lambda: "idx-1",
            git=self.git,
            clock=self.clock,
        )


def test_ac_02_1_criteria_freeze_records_only_criteria_hash() -> None:
    env = Env()

    record = env.service.freeze("criteria")

    assert record.stage is FreezeStage.CRITERIA
    assert record.success_criteria_sha == env.criteria.value.sha()
    assert record.evalset_sha is None and record.prompt_sha is None
    assert record.git_commit == "abc123" and record.frozen_at == T0.isoformat(timespec="seconds")
    assert env.freezes.saved == [record]


def test_criteria_refreeze_same_criteria_keeps_first_time() -> None:
    env = Env()
    first = env.service.freeze("criteria")
    env.clock.value = T0 + timedelta(days=1)

    again = env.service.freeze("criteria")

    assert again == first
    assert len(env.freezes.saved) == 1


def test_criteria_refreeze_with_changed_targets_rejected() -> None:
    env = Env()
    env.service.freeze("criteria")
    env.criteria.value = SuccessCriteria(
        priority=("quality", "latency", "cost"), targets={**TARGETS, "hit_at_5": 10}
    )

    with pytest.raises(RuleViolationError) as exc_info:
        env.service.freeze("criteria")

    assert exc_info.value.code == FROZEN_MISMATCH


def test_final_freeze_records_all_versions() -> None:
    env = Env()
    env.service.freeze("criteria")

    record = env.service.freeze("final")

    assert record.stage is FreezeStage.FINAL
    assert record.evalset_sha and record.prompt_sha == "prompt-v1"
    assert record.index_version == "idx-1"
    assert dict(record.config_sha) == {"A": "a", "B": "b", "C": "c", "C+R": "cr"}


def test_final_freeze_rejected_with_uncommitted_changes() -> None:
    env = Env(dirty=True)

    with pytest.raises(RuleViolationError, match="커밋하지 않은 변경"):
        env.service.freeze("final")

    assert env.freezes.saved == []


def test_final_refreeze_rejected_and_not_overwritten() -> None:
    env = Env()
    final = env.service.freeze("final")
    env.prompt = "prompt-v2"

    for stage in ("final", "criteria"):
        with pytest.raises(RuleViolationError) as exc_info:
            env.service.freeze(stage)
        assert exc_info.value.code == FROZEN_MISMATCH

    assert env.freezes.saved == [final]


def test_final_after_criteria_rejects_changed_criteria() -> None:
    env = Env()
    env.service.freeze("criteria")
    env.criteria.value = SuccessCriteria(priority=("latency", "quality", "cost"), targets=TARGETS)

    with pytest.raises(RuleViolationError):
        env.service.freeze("final")


def test_current_builds_final_record_without_saving() -> None:
    env = Env()

    current = env.service.current()

    assert current.stage is FreezeStage.FINAL
    assert env.freezes.saved == []


def test_ac_02_2_criteria_frozen_before_first_main_run() -> None:
    env = Env()
    env.service.freeze("criteria")

    env.service.check_frozen_before(T0 + timedelta(days=2))
    with pytest.raises(RuleViolationError, match="늦습니다"):
        env.service.check_frozen_before(T0 - timedelta(minutes=1))


def test_ac_02_2_missing_freeze_record_fails_order_check() -> None:
    with pytest.raises(RuleViolationError, match="고정 기록이 없습니다"):
        Env().service.check_frozen_before(T0)

"""TKT-BE-M1-03: 성공 기준·고정 기록 (INV-06, US-02, AC-12-3 도메인 부분)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lawqa.evaluation.domain.errors import FROZEN_MISMATCH, InvalidEvalDataError, RuleViolationError
from lawqa.evaluation.domain.models import FreezeRecord, FreezeStage, SuccessCriteria

TARGETS = {
    "hit_at_5": 14,
    "answer_correct": 12,
    "citation_valid": 13,
    "abstain_correct": 3,
    "latency_median_s": 30,
    "call_success_rate": 0.95,
}


def _final(**changes) -> FreezeRecord:
    record = FreezeRecord(
        stage=FreezeStage.FINAL,
        success_criteria_sha="crit",
        evalset_sha="evalset",
        config_sha={"A": "a", "B": "b", "C": "c", "C+R": "cr"},
        prompt_sha="prompt",
        index_version="idx-1",
        git_commit="abc123",
        frozen_at="2026-11-26T18:00:00+09:00",
    )
    return replace(record, **changes)


def test_success_criteria_d007_targets_valid() -> None:
    criteria = SuccessCriteria(priority=("quality", "latency", "cost"), targets=TARGETS)

    assert criteria.sha() == SuccessCriteria.from_dict(criteria.to_dict()).sha()


@pytest.mark.parametrize(
    ("priority", "targets", "message"),
    [
        (("quality", "latency"), TARGETS, "priority"),
        (("quality", "quality", "cost"), TARGETS, "priority"),
        (("quality", "latency", "cost"), {**TARGETS, "hit_at_5": 18}, "hit_at_5"),
        (("quality", "latency", "cost"), {**TARGETS, "abstain_correct": 4}, "abstain_correct"),
        (
            ("quality", "latency", "cost"),
            {**TARGETS, "call_success_rate": 1.5},
            "call_success_rate",
        ),
        (("quality", "latency", "cost"), {**TARGETS, "latency_median_s": 0}, "latency_median_s"),
        (
            ("quality", "latency", "cost"),
            {k: v for k, v in TARGETS.items() if k != "hit_at_5"},
            "키",
        ),
    ],
)
def test_success_criteria_rejects_invalid(priority, targets, message: str) -> None:
    with pytest.raises(InvalidEvalDataError, match=message):
        SuccessCriteria(priority=priority, targets=targets)


def test_success_criteria_sha_changes_when_target_changes() -> None:
    first = SuccessCriteria(priority=("quality", "latency", "cost"), targets=TARGETS)
    second = SuccessCriteria(
        priority=("quality", "latency", "cost"), targets={**TARGETS, "hit_at_5": 13}
    )

    assert first.sha() != second.sha()


def test_verify_same_values_passes_even_if_commit_and_time_differ() -> None:
    _final().verify(_final(git_commit="later", frozen_at="2026-11-27T10:00:00+09:00"))


@pytest.mark.parametrize(
    "changes",
    [
        {"success_criteria_sha": "crit2"},
        {"evalset_sha": "evalset2"},
        {"config_sha": {"A": "a", "B": "b", "C": "changed", "C+R": "cr"}},
        {"prompt_sha": "prompt2"},
        {"index_version": "idx-2"},
    ],
)
def test_ac_12_3_verify_rejects_any_changed_frozen_value(changes) -> None:
    with pytest.raises(RuleViolationError) as exc_info:
        _final().verify(_final(**changes))

    assert exc_info.value.code == FROZEN_MISMATCH
    assert next(iter(changes)) in exc_info.value.detail


def test_criteria_stage_verifies_only_success_criteria() -> None:
    criteria = FreezeRecord(stage=FreezeStage.CRITERIA, success_criteria_sha="crit")

    criteria.verify(_final(evalset_sha="anything"))
    with pytest.raises(RuleViolationError):
        criteria.verify(_final(success_criteria_sha="crit2"))


def test_final_stage_requires_all_hashes() -> None:
    with pytest.raises(InvalidEvalDataError, match="final"):
        FreezeRecord(stage=FreezeStage.FINAL, success_criteria_sha="crit")


def test_freeze_record_round_trip() -> None:
    record = _final()

    assert FreezeRecord.from_dict(record.to_dict()) == record

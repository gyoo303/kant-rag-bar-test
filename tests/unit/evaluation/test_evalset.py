"""TKT-BE-M1-03: 평가셋 규칙 (INV-12, AC-04-1·3)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from lawqa.evaluation.domain.errors import InvalidEvalDataError
from lawqa.evaluation.domain.models import EvalQuestion, EvalSet, QuestionType, Split

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eval"


def _data(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_fixture_dev_and_test_sets_are_valid() -> None:
    dev = EvalSet.from_dict(_data("dev"))
    test = EvalSet.from_dict(_data("test"))

    assert dev.split is Split.DEV and len(dev.questions) == 10 and dev.answerable_count == 8
    assert test.split is Split.TEST and len(test.questions) == 20 and test.answerable_count == 17


def test_ac_04_1_dev_and_test_question_ids_do_not_overlap() -> None:
    dev_ids = {q.question_id for q in EvalSet.from_dict(_data("dev")).questions}
    test_ids = {q.question_id for q in EvalSet.from_dict(_data("test")).questions}

    assert dev_ids.isdisjoint(test_ids)


def test_ac_04_1_test_composition_must_be_10_7_3() -> None:
    data = _data("test")
    data["questions"][0]["type"] = "paraphrase"  # 직접 9·변형 8

    with pytest.raises(InvalidEvalDataError, match="INV-12"):
        EvalSet.from_dict(data)


def test_ac_04_1_dev_composition_must_be_8_answerable_2_no_evidence() -> None:
    data = _data("dev")
    data["questions"] = data["questions"][:9]

    with pytest.raises(InvalidEvalDataError, match="INV-12"):
        EvalSet.from_dict(data)


@pytest.mark.parametrize("bad_id", ["TEST-01", "DEV-1", "DEV-001"])
def test_dev_question_id_must_use_dev_prefix_and_two_digits(bad_id: str) -> None:
    data = _data("dev")
    data["questions"][0]["question_id"] = bad_id

    with pytest.raises(InvalidEvalDataError, match="DEV-NN"):
        EvalSet.from_dict(data)


def test_duplicate_question_ids_rejected() -> None:
    data = _data("dev")
    data["questions"][1]["question_id"] = data["questions"][0]["question_id"]

    with pytest.raises(InvalidEvalDataError, match="중복"):
        EvalSet.from_dict(data)


def _no_evidence_question() -> dict[str, Any]:
    return copy.deepcopy(_data("test")["questions"][-1])


def _answerable_question() -> dict[str, Any]:
    return copy.deepcopy(_data("test")["questions"][0])


def test_ac_04_3_no_evidence_question_valid_shape() -> None:
    question = EvalQuestion.from_dict(_no_evidence_question())

    assert question.type is QuestionType.NO_EVIDENCE
    assert question.expected.answer is None and question.expected.insufficient
    assert question.allowed_evidence == () and question.absence_reason


@pytest.mark.parametrize(
    ("field_path", "value", "message"),
    [
        (("expected", "answer"), 3, "expected.answer=null"),
        (("expected", "insufficient"), False, "insufficient=true"),
        (("absence_reason",), "", "absence_reason"),
    ],
)
def test_ac_04_3_no_evidence_question_rules(
    field_path: tuple[str, ...], value: Any, message: str
) -> None:
    data = _no_evidence_question()
    target = data
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(InvalidEvalDataError, match=message):
        EvalQuestion.from_dict(data)


def test_ac_04_3_no_evidence_question_must_have_empty_evidence() -> None:
    data = _no_evidence_question()
    data["allowed_evidence"] = _answerable_question()["allowed_evidence"]

    with pytest.raises(InvalidEvalDataError, match="allowed_evidence가 비어야"):
        EvalQuestion.from_dict(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["expected"].update(answer=6), "1~5"),
        (lambda d: d["expected"].update(answer=None), "1~5"),
        (lambda d: d["expected"].update(key_facts=[]), "key_facts"),
        (lambda d: d.update(allowed_evidence=[]), "allowed_evidence"),
        (lambda d: d["item"].update(options=["a", "b", "c", "d"]), "보기 5개"),
        (lambda d: d["item"].update(stem="  "), "stem"),
        (lambda d: d.update(source="exam:2025:1"), "source"),
        (lambda d: d.update(answer_source="unknown"), "answer_source"),
    ],
)
def test_ac_04_2_answerable_question_rules(mutate, message: str) -> None:
    data = _answerable_question()
    mutate(data)

    with pytest.raises(InvalidEvalDataError, match=message):
        EvalQuestion.from_dict(data)


def test_missing_field_reports_question_id() -> None:
    data = _answerable_question()
    del data["expected"]

    with pytest.raises(InvalidEvalDataError, match="TEST-01"):
        EvalQuestion.from_dict(data)


def test_evalset_sha_is_stable_and_changes_with_content() -> None:
    data = _data("test")
    first = EvalSet.from_dict(data).sha()
    again = EvalSet.from_dict(_data("test")).sha()
    data["questions"][0]["expected"]["key_facts"] = ["바뀐 사실"]

    assert first == again
    assert EvalSet.from_dict(data).sha() != first


def test_evalset_round_trip_to_dict() -> None:
    data = _data("dev")

    assert EvalSet.from_dict(data).to_dict() == data

"""TKT-BE-M3-02: Answer 규칙 (INV-01·03·13, R-2, ADR-013 검증 순서, §4 오류 코드)."""

from __future__ import annotations

import pytest

from lawqa.answering.domain.errors import ModelOutputFormatError
from lawqa.answering.domain.models import (
    INSUFFICIENT_MESSAGE,
    Answer,
    ErrorCode,
    ModelAnswer,
    ModelOption,
    OptionJudgment,
    Outcome,
    Verdict,
)

CANDIDATES = {"c1", "c2", "c3"}
LOCATIONS = {"c1": "민법 제548조 제1항", "c2": "대법원 2008. 10. 23. 선고 …", "c3": "민법 제2조"}


def _out(answer=3, sufficient=True, cites=None, verdicts=None, **kw) -> ModelAnswer:
    cites = cites or {3: ["c1"]}
    verdicts = verdicts or {}
    return ModelAnswer(
        answer=answer,
        sufficient=sufficient,
        options=tuple(
            ModelOption(n, verdicts.get(n, "incorrect"), f"이유{n}", tuple(cites.get(n, [])))
            for n in kw.get("nos", (1, 2, 3, 4, 5))
        ),
    )


def _answer(output: ModelAnswer) -> Answer:
    return Answer.from_model_output(output, CANDIDATES, LOCATIONS)


# ── ④ 답변 ──
def test_answered_with_citation_and_location():
    a = _answer(_out(verdicts={3: "correct"}))
    assert a.outcome is Outcome.ANSWERED and a.answer_no == 3
    assert a.judgments[2].citations[0].location == "민법 제548조 제1항"
    assert a.judgments[2].verdict is Verdict.CORRECT
    assert a.error_code is None and a.user_message == "정답: 3번"


def test_chosen_option_may_be_incorrect_for_negative_questions():
    """ "옳지 않은 것은?" 문항에서는 틀린 보기를 고른다 — 판단이 insufficient만 아니면 된다."""
    assert _answer(_out(verdicts={3: "INCORRECT"})).outcome is Outcome.ANSWERED


# ── ② 후보 밖 인용 제거 (INV-01) ──
def test_citations_outside_candidates_are_dropped_and_counted():
    a = _answer(_out(cites={3: ["c1", "ghost", "c1"], 1: ["nope"]}))
    assert [c.chunk_id for c in a.judgments[2].citations] == ["c1"]  # 중복도 한 번
    assert a.dropped_citations == 2
    assert all(c.chunk_id in CANDIDATES for j in a.judgments for c in j.citations)


def test_only_invented_citations_for_answer_becomes_insufficient():
    a = _answer(_out(cites={3: ["ghost"]}))
    assert a.outcome is Outcome.INSUFFICIENT_EVIDENCE and a.answer_no is None
    assert a.dropped_citations == 1


# ── ③ 근거 부족 (INV-13, R-2) ──
def test_answer_option_without_citation_is_insufficient():
    a = _answer(_out(cites={1: ["c2"]}))
    assert a.outcome is Outcome.INSUFFICIENT_EVIDENCE
    assert a.answer_no is None and a.user_message == INSUFFICIENT_MESSAGE
    assert a.judgments[0].citations[0].chunk_id == "c2"  # 다른 보기 판단은 참고로 유지


@pytest.mark.parametrize(
    "output",
    [
        _out(sufficient=False),
        _out(answer=None),
        _out(verdicts={3: "insufficient"}),
    ],
)
def test_insufficient_cases(output):
    a = _answer(output)
    assert a.outcome is Outcome.INSUFFICIENT_EVIDENCE and a.answer_no is None
    assert len(a.judgments) == 5


# ── ① 형식 ──
@pytest.mark.parametrize(
    "output",
    [
        _out(nos=(1, 2, 3, 4)),
        _out(nos=(1, 2, 3, 3, 5)),
        _out(answer=6),
        _out(verdicts={2: "maybe"}),
    ],
)
def test_format_errors(output):
    with pytest.raises(ModelOutputFormatError):
        _answer(output)


def test_from_dict_parses_schema_and_rejects_wrong_types():
    data = {
        "answer": 2,
        "sufficient": True,
        "options": [
            {"no": n, "verdict": "correct", "reason": "r", "citations": ["c1"]} for n in range(1, 6)
        ],
    }
    parsed = ModelAnswer.from_dict(data, raw_output="{...}")
    assert parsed.answer == 2 and parsed.options[0].citations == ("c1",)
    assert parsed.raw_output == "{...}"
    for broken in (
        {**data, "answer": "2"},
        {**data, "sufficient": "yes"},
        {**data, "options": "x"},
        {k: v for k, v in data.items() if k != "options"},
        {**data, "options": [{"no": "1", "verdict": "correct"}]},
    ):
        with pytest.raises(ModelOutputFormatError):
            ModelAnswer.from_dict(broken)


# ── 오류 결과 (INV-03, §4) ──
@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (Outcome.INPUT_ERROR, ErrorCode.INVALID_INPUT),
        (Outcome.RETRIEVAL_ERROR, ErrorCode.RETRIEVAL_FAILED),
        (Outcome.RETRIEVAL_ERROR, ErrorCode.RERANKER_FAILED),
        (Outcome.MODEL_ERROR, ErrorCode.MODEL_TIMEOUT),
        (Outcome.MODEL_ERROR, ErrorCode.UNEXPECTED),
    ],
)
def test_error_results_have_no_number(outcome, code):
    a = Answer.error(outcome, code, "검색 오류")
    assert a.answer_no is None and a.error_code is code and a.judgments == ()


def test_error_code_must_match_outcome():
    with pytest.raises(ValueError):
        Answer.error(Outcome.RETRIEVAL_ERROR, ErrorCode.MODEL_TIMEOUT, "x")
    with pytest.raises(ValueError):
        Answer.error(Outcome.ANSWERED, ErrorCode.UNEXPECTED, "x")


def test_answered_invariants_enforced_on_construction():
    no_cite = OptionJudgment(1, Verdict.CORRECT, "r")
    with pytest.raises(ValueError):
        Answer(Outcome.ANSWERED, 1, (no_cite,), None, "정답: 1번")
    with pytest.raises(ValueError):
        Answer(Outcome.INSUFFICIENT_EVIDENCE, 1, (), None, INSUFFICIENT_MESSAGE)
    with pytest.raises(ValueError):
        Answer(Outcome.MODEL_ERROR, 2, (), ErrorCode.UNEXPECTED, "답변 생성 오류")

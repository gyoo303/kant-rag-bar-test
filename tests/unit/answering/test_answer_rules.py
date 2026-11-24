"""TKT-BE-M3-02: Answer 규칙 (INV-01·03·13, R-2, ADR-013 검증 순서, §4 오류 코드)."""

from __future__ import annotations

import pytest

from lawqa.answering.domain.errors import ModelOutputFormatError
from lawqa.answering.domain.models import (
    UNCERTAIN_MESSAGE,
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


def test_only_invented_citations_for_answer_is_not_sufficient():
    """CR-014: 인용이 모두 가짜여도 번호는 내고 근거 충족만 false가 된다."""
    a = _answer(_out(cites={3: ["ghost"]}))
    assert a.outcome is Outcome.ANSWERED and a.answer_no == 3
    assert a.evidence_sufficient is False
    assert a.dropped_citations == 1


# ── ③·④ 번호는 항상, 근거 충족은 따로 (INV-13, R-2, CR-014) ──
def test_answer_option_without_citation_keeps_number_but_not_sufficient():
    a = _answer(_out(cites={1: ["c2"]}))
    assert a.outcome is Outcome.ANSWERED and a.answer_no == 3
    assert a.evidence_sufficient is False
    assert UNCERTAIN_MESSAGE in a.user_message
    assert a.judgments[0].citations[0].chunk_id == "c2"  # 다른 보기 판단은 참고로 유지


@pytest.mark.parametrize(
    "output",
    [
        _out(sufficient=False),
        _out(answer=None),
        _out(verdicts={3: "insufficient"}),
    ],
)
def test_uncertain_cases_still_give_a_number(output):
    a = _answer(output)
    assert a.outcome is Outcome.ANSWERED
    assert a.answer_no in (1, 2, 3, 4, 5)
    assert a.evidence_sufficient is False
    assert len(a.judgments) == 5


def test_null_answer_falls_back_to_a_correct_option():
    """모델이 번호를 비우면 correct로 판단한 보기 중 가장 작은 번호를 쓴다(CR-014)."""
    a = _answer(_out(answer=None, verdicts={2: "correct", 4: "correct"}))
    assert a.answer_no == 2 and a.evidence_sufficient is False


def test_sufficient_answer_records_the_flag():
    a = _answer(_out())
    assert a.outcome is Outcome.ANSWERED and a.answer_no == 3
    assert a.evidence_sufficient is True


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
        Answer(Outcome.ANSWERED, 1, (no_cite,), None, "정답: 1번", evidence_sufficient=True)
    with pytest.raises(ValueError):
        Answer(Outcome.ANSWERED, None, (), None, "정답 없음")
    with pytest.raises(ValueError):
        Answer(
            Outcome.MODEL_ERROR, None, (), ErrorCode.UNEXPECTED, "오류", evidence_sufficient=True
        )
    with pytest.raises(ValueError):
        Answer(Outcome.MODEL_ERROR, 2, (), ErrorCode.UNEXPECTED, "답변 생성 오류")

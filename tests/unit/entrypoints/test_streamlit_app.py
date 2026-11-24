"""TKT-FE-M3-01: SCR-01 화면 (AC-11-1·2·3, 상태 6종). Streamlit `AppTest` + 대역 AnswerService."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from lawqa.answering.application.answer_service import AnswerEnvelope
from lawqa.answering.domain.models import (
    Answer,
    Citation,
    ErrorCode,
    OptionJudgment,
    Outcome,
    Verdict,
)
from lawqa.retrieval.domain.models import Candidate, OptionQuery

APP = Path(__file__).resolve().parents[3] / "src" / "lawqa" / "entrypoints" / "streamlit_app.py"
NOTICE = "학습용 결과이며 법률 자문이 아닙니다."
LOC = "민법 제548조"


def _envelope(answer: Answer, config: str = "C+R", fallback: bool = False) -> AnswerEnvelope:
    queries = tuple(
        OptionQuery(n, f"원{n}", None if fallback else f"법률 질의 {n}", fallback=fallback)
        for n in range(1, 6)
    )
    return AnswerEnvelope(
        answer=answer,
        config_name=config,
        retrieval=None,
        context=(
            Candidate("c1", "d1", LOC, "계약이 해제된 때에는 각 당사자는 원상회복의 의무가 있다."),
        ),
        prompt_sha="sha",
        raw_output="{}",
        latency_ms=12345,
        queries=queries,
    )


def _judgments(cite_option: int | None) -> tuple[OptionJudgment, ...]:
    return tuple(
        OptionJudgment(
            n,
            Verdict.CORRECT if n == 3 else Verdict.INCORRECT,
            f"이유 {n}",
            (Citation("c1", LOC),) if n == cite_option else (),
        )
        for n in range(1, 6)
    )


ANSWERED = Answer(Outcome.ANSWERED, 3, _judgments(3), None, "정답: 3번")
INSUFFICIENT = Answer(
    Outcome.INSUFFICIENT_EVIDENCE, None, _judgments(1), None, "정보 부족: 근거를 찾지 못했습니다"
)
INPUT_ERROR = Answer.error(
    Outcome.INPUT_ERROR, ErrorCode.INVALID_INPUT, "입력 오류: 지문이 비어 있습니다."
)
RETRIEVAL_ERROR = Answer.error(Outcome.RETRIEVAL_ERROR, ErrorCode.RETRIEVAL_FAILED, "검색 오류")
MODEL_ERROR = Answer.error(Outcome.MODEL_ERROR, ErrorCode.MODEL_TIMEOUT, "답변 생성 오류")


class StubService:
    def __init__(self, envelope: AnswerEnvelope) -> None:
        self.envelope = envelope
        self.calls: list[tuple[dict, str]] = []

    def answer(self, item, config_name):
        self.calls.append((item, config_name))
        return self.envelope


class StubRuntime:
    def __init__(self, envelope: AnswerEnvelope, warning: str | None = None) -> None:
        self.service = StubService(envelope)
        self.warning = warning

    def index_warning(self):
        return self.warning


def _app(runtime: StubRuntime) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["answer_runtime"] = runtime
    return at.run()


def _submit(
    at: AppTest, stem: str = "계약 해제에 관한 설명으로 옳은 것은?", options=None
) -> AppTest:
    at.text_area(key="stem").input(stem)
    for i, text in enumerate(options or ["가", "나", "다", "라", "마"]):
        at.text_input(key=f"option_{i}").input(text)
    at.button[0].click()
    return at.run()


def _texts(at: AppTest) -> str:
    parts = [e.value for e in at.caption] + [e.value for e in at.markdown]
    parts += [e.value for e in at.success] + [e.value for e in at.info]
    parts += (
        [e.value for e in at.warning] + [e.value for e in at.error] + [e.value for e in at.text]
    )
    return "\n".join(str(p) for p in parts)


# ── AC-11-2: 학습용 안내는 언제나 ──
def test_ac_11_2_notice_visible_before_submit():
    at = _app(StubRuntime(_envelope(ANSWERED)))
    assert not at.exception
    assert NOTICE in [c.value for c in at.caption]
    assert len(at.text_input) == 5 and at.selectbox(key="config").value == "C+R"


@pytest.mark.parametrize(
    "answer", [ANSWERED, INSUFFICIENT, INPUT_ERROR, RETRIEVAL_ERROR, MODEL_ERROR]
)
def test_ac_11_2_notice_visible_in_every_result_state(answer):
    at = _submit(_app(StubRuntime(_envelope(answer))))
    assert not at.exception
    assert NOTICE in [c.value for c in at.caption]


# ── AC-11-1: 제출 → 결과 종류별 표시 ──
def test_ac_11_1_answered_shows_number_judgments_citations_and_search_info():
    runtime = StubRuntime(_envelope(ANSWERED))
    at = _submit(_app(runtime))

    assert runtime.service.calls == [
        (
            {
                "stem": "계약 해제에 관한 설명으로 옳은 것은?",
                "options": ["가", "나", "다", "라", "마"],
            },
            "C+R",
        )
    ]
    assert at.success[0].value == "결과 종류: 성공 — 정답: ③"
    judgments, citations = at.dataframe[0].value, at.dataframe[1].value
    assert list(judgments["판단"]) == ["틀림", "틀림", "옳음", "틀림", "틀림"]
    assert judgments["인용"][2] == LOC
    assert list(citations["청크 ID"]) == ["c1"]
    assert citations["출처"][0].startswith("https://www.law.go.kr/LSW/totalSearch.do?query=")
    text = _texts(at)
    assert "원상회복의 의무" in text  # 인용 본문 펼치기
    assert "구성: C+R" in text and "법률 질의 1" in text and "소요 시간: 12.3초" in text
    assert at.button[0].disabled is False  # 처리가 끝나면 다시 제출 가능


def test_ac_11_1_insufficient_shows_info_without_number_and_reference_judgments():
    at = _submit(_app(StubRuntime(_envelope(INSUFFICIENT))))
    assert at.info[0].value == "결과 종류: 근거 부족 — 정보 부족: 근거를 찾지 못했습니다"
    assert not at.success and not at.error
    assert "보기별 판단 (참고)" in _texts(at)
    assert "정답:" not in _texts(at)


def test_ac_11_1_input_error_shows_only_warning():
    at = _submit(_app(StubRuntime(_envelope(INPUT_ERROR))), stem="")
    assert at.warning[0].value == "결과 종류: 입력 오류 — 입력 오류: 지문이 비어 있습니다."
    assert len(at.dataframe) == 0 and len(at.expander) == 0  # 결과 영역에 다른 내용 없음
    assert at.text_input(key="option_0").value == "가"  # 입력 유지


def test_retrieval_error_shows_error_distinct_from_insufficient():
    at = _submit(_app(StubRuntime(_envelope(RETRIEVAL_ERROR))))
    assert at.error[0].value == "결과 종류: 검색 실패 — 검색 오류"
    assert not at.info


# ── AC-11-3: 모델 오류는 근거 부족과 다른 문구·표시 ──
def test_ac_11_3_model_error_differs_from_insufficient():
    model = _submit(_app(StubRuntime(_envelope(MODEL_ERROR))))
    insufficient = _submit(_app(StubRuntime(_envelope(INSUFFICIENT))))
    assert model.error[0].value == "결과 종류: 모델 오류 — 답변 생성 오류"
    assert not model.info  # 표시 종류도 다름(error vs info)
    assert model.error[0].value != insufficient.info[0].value


# ── 처리 중·그 밖 ──
def test_processing_state_disables_submit_button():
    at = _app(StubRuntime(_envelope(ANSWERED)))
    at.session_state["running"] = True
    at.session_state["pending"] = {"stem": "지문", "options": ["a"] * 5, "config": "A"}
    at.run()
    assert not at.exception
    assert at.success[0].value.startswith("결과 종류: 성공")
    assert at.session_state["running"] is False


def test_config_choice_and_fallback_are_shown():
    runtime = StubRuntime(_envelope(ANSWERED, config="A", fallback=True))
    at = _app(runtime)
    at.selectbox(key="config").select("A")
    at = _submit(at)
    assert runtime.service.calls[0][1] == "A"
    assert "리라이트 실패 — 원 질의로 검색(fallback)" in _texts(at)


def test_incomplete_index_warning_is_shown():
    at = _submit(_app(StubRuntime(_envelope(ANSWERED), warning="불완전 색인 idx-1로 검색합니다")))
    assert "불완전 색인 idx-1" in _texts(at)


def test_model_text_is_not_rendered_as_markup():
    hostile = Answer(
        Outcome.ANSWERED,
        3,
        tuple(
            OptionJudgment(
                n,
                Verdict.CORRECT,
                "<script>alert(1)</script> **굵게**",
                (Citation("c1", LOC),) if n == 3 else (),
            )
            for n in range(1, 6)
        ),
        None,
        "정답: 3번",
    )
    at = _submit(_app(StubRuntime(_envelope(hostile))))
    assert (
        at.dataframe[0].value["이유"][0] == "<script>alert(1)</script> **굵게**"
    )  # 표 셀은 글자 그대로
    assert all("<script>" not in m.value for m in at.markdown)

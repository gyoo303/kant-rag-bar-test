"""SCR-01 문항 풀이 화면 (PAGE-01, 04-interfaces-api §7, 07-screens SCR-01).

실행: `uv run streamlit run src/lawqa/entrypoints/streamlit_app.py`

- 제출하면 `AnswerService.answer({"stem","options"}, config_name)`를 동기 호출하고 받은
  `AnswerEnvelope`를 그대로 그린다. 결과 판정·인용 검증은 하지 않는다(도메인 몫).
- 검색기·재정렬 모델·DB 연결은 `st.cache_resource`로 프로세스당 한 번 만든다(답변은 캐시 안 함).
- 시험은 `st.session_state["answer_runtime"]`에 대역을 넣어 실제 조립을 건너뛴다.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import streamlit as st

from lawqa.answering.application.answer_service import AnswerEnvelope
from lawqa.answering.domain.models import Outcome, Verdict

log = logging.getLogger(__name__)

NOTICE = "학습용 결과이며 법률 자문이 아닙니다."
CONFIGS = ("C+R", "A", "B", "C")  # C+R 기본(§7)
OPTION_MARKS = ("①", "②", "③", "④", "⑤")
OUTCOME_LABELS = {
    Outcome.ANSWERED: "성공",
    Outcome.INSUFFICIENT_EVIDENCE: "근거 부족",
    Outcome.INPUT_ERROR: "입력 오류",
    Outcome.RETRIEVAL_ERROR: "검색 실패",
    Outcome.MODEL_ERROR: "모델 오류",
}
VERDICT_LABELS = {
    Verdict.CORRECT: "옳음",
    Verdict.INCORRECT: "틀림",
    Verdict.INSUFFICIENT: "근거 부족",
}
LAW_SEARCH_URL = "https://www.law.go.kr/LSW/totalSearch.do?query="  # 사용자 결정 2026-11-24


def source_link(location: str) -> str:
    """원문 위치 글로 국가법령정보센터 통합검색 주소를 만든다."""
    return LAW_SEARCH_URL + quote(location)


@st.cache_resource(show_spinner=False)
def _cached_runtime() -> Any:
    """실제 조립(DB 연결은 프로세스가 끝날 때까지 열어 둠)."""
    from lawqa.entrypoints.composition import build_answer_runtime
    from lawqa.shared.db import connect
    from lawqa.shared.settings import load_settings

    settings = load_settings("base")
    url = settings.secrets.require("database_url")
    conn = connect(url)
    return build_answer_runtime(conn, url, settings=settings)


def _runtime() -> Any:
    injected = st.session_state.get("answer_runtime")
    return injected if injected is not None else _cached_runtime()


def _start() -> None:
    """제출 버튼: 입력을 잡아 두고 처리 중으로 바꾼다(버튼 비활성)."""
    st.session_state["pending"] = {
        "stem": st.session_state.get("stem", ""),
        "options": [st.session_state.get(f"option_{i}", "") for i in range(5)],
        "config": st.session_state.get("config", CONFIGS[0]),
    }
    st.session_state["running"] = True


def main() -> None:
    st.set_page_config(page_title="민법 선택형 문항 풀이")
    st.title("민법 선택형 문항 풀이")
    st.caption(NOTICE)  # 모든 상태에서 보임(R-4, AC-11-2)

    running = bool(st.session_state.get("running"))
    with st.form("question"):
        st.text_area("지문", key="stem", height=120)
        for i, mark in enumerate(OPTION_MARKS):
            st.text_input(f"보기 {mark}", key=f"option_{i}")
        st.selectbox("검색 구성", CONFIGS, key="config")
        st.form_submit_button("제출", on_click=_start, disabled=running)

    if running:
        pending = st.session_state.pop("pending")
        with st.spinner("처리 중…"):
            st.session_state["envelope"] = _answer(pending)
        st.session_state["running"] = False
        st.rerun()

    envelope = st.session_state.get("envelope")
    if envelope is not None:
        render_result(envelope)


def _answer(pending: dict[str, Any]) -> AnswerEnvelope | str:
    """답변을 받는다. 화면 준비(DB·모델 조립) 자체가 실패하면 그 사실만 문자열로 돌려준다."""
    try:
        runtime = _runtime()
    except Exception:  # 조립 실패는 화면에 오류로 보이고 원문은 로그에만(§4)
        log.exception("streamlit_runtime_failed")
        return "검색 오류"
    warning = runtime.index_warning()
    if warning:
        st.session_state["index_warning"] = warning
    item = {"stem": pending["stem"], "options": pending["options"]}
    return runtime.service.answer(item, pending["config"])


def render_result(envelope: AnswerEnvelope | str) -> None:
    st.divider()
    st.subheader("결과")
    if isinstance(envelope, str):
        st.error(f"결과 종류: {OUTCOME_LABELS[Outcome.RETRIEVAL_ERROR]} — {envelope}")
        return
    warning = st.session_state.get("index_warning")
    if warning:
        st.caption(f"⚠ {warning}")

    answer = envelope.answer
    label = f"결과 종류: {OUTCOME_LABELS[answer.outcome]}"
    if answer.outcome is Outcome.ANSWERED:
        st.success(f"{label} — 정답: {OPTION_MARKS[answer.answer_no - 1]}")
        _judgments(envelope, reference=False)
        _citations(envelope)
    elif answer.outcome is Outcome.INSUFFICIENT_EVIDENCE:
        st.info(f"{label} — {answer.user_message}")
        if any(j.citations for j in answer.judgments):
            _judgments(envelope, reference=True)  # R-2: 근거 있는 보기의 판단은 참고로
    elif answer.outcome is Outcome.INPUT_ERROR:
        st.warning(f"{label} — {answer.user_message}")
        return  # 결과 영역에 다른 내용 없음(07-screens §4)
    else:
        st.error(f"{label} — {answer.user_message}")
    _search_info(envelope)


def _judgments(envelope: AnswerEnvelope, *, reference: bool) -> None:
    st.markdown("**보기별 판단 (참고)**" if reference else "**보기별 판단**")
    st.dataframe(
        [
            {
                "보기": OPTION_MARKS[j.option_no - 1],
                "판단": VERDICT_LABELS[j.verdict],
                "이유": j.reason,
                "인용": ", ".join(c.location for c in j.citations) or "-",
            }
            for j in envelope.answer.judgments
        ],
        hide_index=True,
        use_container_width=True,
    )


def _citations(envelope: AnswerEnvelope) -> None:
    cited: dict[str, str] = {}
    for judgment in envelope.answer.judgments:
        for citation in judgment.citations:
            cited.setdefault(citation.chunk_id, citation.location)
    st.markdown("**인용 목록**")
    st.dataframe(
        [
            {"청크 ID": chunk_id, "원문 위치": location, "출처": source_link(location)}
            for chunk_id, location in cited.items()
        ],
        column_config={"출처": st.column_config.LinkColumn("출처", display_text="원문 찾기")},
        hide_index=True,
        use_container_width=True,
    )
    texts = {c.chunk_id: c.text for c in envelope.context}
    for chunk_id, location in cited.items():
        with st.expander(f"{location} 본문"):
            st.text(texts.get(chunk_id, "(본문 없음)"))


def _search_info(envelope: AnswerEnvelope) -> None:
    with st.expander("검색 정보"):
        st.text(f"구성: {envelope.config_name}")
        for query in envelope.queries:
            mark = OPTION_MARKS[query.option_no - 1]
            if query.fallback:
                st.text(f"보기 {mark}: 리라이트 실패 — 원 질의로 검색(fallback)")
            elif query.rewritten is not None:
                st.text(f"보기 {mark}: {query.rewritten}")
            else:
                st.text(f"보기 {mark}: 원 질의(리라이트 없음)")
        st.text(f"소요 시간: {envelope.latency_ms / 1000:.1f}초")


main()

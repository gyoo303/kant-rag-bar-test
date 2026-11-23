"""실행 인터페이스: 질문 → 답변·근거·오류 확인.  `uv run streamlit run app/streamlit_app.py`"""

import streamlit as st

from kant_rag.agent import KnowledgeAgent
from kant_rag.config import get_settings
from kant_rag.retrieval.pipeline import RetrievalMode

st.set_page_config(page_title="민사법 RAG Agent", layout="wide")
st.title("⚖️ 민사법 RAG Agent")


@st.cache_resource
def load_agent() -> KnowledgeAgent:
    return KnowledgeAgent(get_settings())


settings = get_settings()
with st.sidebar:
    mode = st.radio("검색 구성", [m.value for m in RetrievalMode], index=2,
                    help="A=vector, B=hybrid(BM25+Vector RRF), C=hybrid+rerank")
    st.caption(f"versions: {settings.versions.model_dump()}")
    st.caption(f"LLM: {settings.models.llm_provider}/{settings.models.llm_model}")

tab_qa, tab_mcq = st.tabs(["질의응답", "선택형 풀이"])

with tab_mcq:
    from kant_rag.mcq.parse import parse_exam_text
    from kant_rag.mcq.solver import MCQSolver

    raw = st.text_area("문항 붙여넣기 (【문 N】 발문, ①~⑤ 보기, 조합형은 ㄱ.~ㅁ.)", height=260)
    if st.button("풀이", type="primary", key="solve") and raw.strip():
        qs = parse_exam_text(raw if "【문" in raw else "【문 1】 " + raw, id_prefix="UI")
        if not qs:
            st.error("문항을 인식하지 못했습니다.")
        else:
            q = qs[0]
            with st.spinner("진술별 검색 및 판단 중..."):
                rec = MCQSolver(get_settings(), load_agent().retriever).solve(q, RetrievalMode(mode))
            st.caption(f"형식={q.form} · 극성={q.polarity} · 상태={rec['status']}")
            if rec.get("predicted"):
                st.success(f"예측 정답: {'①②③④⑤'[rec['predicted'] - 1]}")
            elif rec["status"] == "insufficient_evidence":
                st.warning("근거 부족: 판단할 수 있는 진술이 없습니다.")
            else:
                st.error(f"{rec['status']}: {rec.get('error')}")
            for key, j in (rec.get("judgments") or {}).items():
                icon = {"true": "⭕", "false": "❌", "unknown": "❔"}[j["verdict"]]
                with st.expander(f"{icon} {key}. {q.statements()[key][:60]}  ({j['confidence']:.2f})"):
                    st.write(j["reason"])
                    st.caption("근거: " + ", ".join(j["cited_chunk_ids"]))
            with st.expander("진술별 검색 결과 / 시간"):
                st.json({"timing_ms": rec["timing_ms"], "retrieval": rec.get("retrieval"),
                         "option_scores": rec.get("option_scores")})

with tab_qa:
    question = st.text_input("민사법 질문을 입력하세요", placeholder="예) 불법행위 손해배상청구권의 소멸시효는?")
    if st.button("질문하기", type="primary") and question.strip():
        with st.spinner("검색 및 답변 생성 중..."):
            rec = load_agent().ask(question, mode=RetrievalMode(mode))
        ans = rec["answer"]
        status = ans["status"]
        if status == "ok":
            st.success("근거 기반 답변")
        elif status == "insufficient_evidence":
            st.warning("근거 부족")
        else:
            st.error(f"오류: {status} — {ans.get('error')}")
        st.markdown(ans["answer"] or "_(답변 없음)_")

        if ans["citations"]:
            st.subheader("출처")
            for c in ans["citations"]:
                with st.expander(f"{c['title']} · {c['location']} · `{c['chunk_id']}`"):
                    st.text(c["quote"])

        with st.expander("검색 단계별 후보 / 시간"):
            st.json({"timing_ms": rec["timing_ms"], "retrieval": rec.get("retrieval"),
                     "rewrite": rec.get("rewrite"), "cache": rec.get("cache")})

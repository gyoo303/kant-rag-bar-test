"""실행 인터페이스: 질문 → 답변·근거·오류 확인.  `uv run streamlit run app/streamlit_app.py`"""

import streamlit as st

from kant_rag.agent import KnowledgeAgent
from kant_rag.config import get_settings
from kant_rag.retrieval.pipeline import RetrievalMode

st.set_page_config(page_title="Knowledge Agent", layout="wide")
st.title("📚 Knowledge Agent")


@st.cache_resource
def load_agent() -> KnowledgeAgent:
    return KnowledgeAgent(get_settings())


settings = get_settings()
with st.sidebar:
    mode = st.radio("검색 구성", [m.value for m in RetrievalMode], index=2,
                    help="A=vector, B=hybrid(BM25+Vector RRF), C=hybrid+rerank")
    st.caption(f"versions: {settings.versions.model_dump()}")
    st.caption(f"LLM: {settings.models.llm_provider}/{settings.models.llm_model}")

question = st.text_input("업무 질문을 입력하세요", placeholder="예) 개봉 후 반품 가능한 조건은?")
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

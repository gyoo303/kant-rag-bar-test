"""실행 화면:  uv run streamlit run app/streamlit_app.py

질문 → 답변 · 판단 · 근거(원문 발췌) · 상태(정상/근거 없음/오류) · 단계별 후보와 점수.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from civil_rag import config
from civil_rag.agent import RUN_CONFIGS, LegalRAG

st.set_page_config(page_title="민사법 판례 RAG", page_icon="⚖️", layout="wide")


@st.cache_resource(show_spinner="청크·BM25 색인 불러오는 중…")
def get_rag() -> LegalRAG:
    rag = LegalRAG()
    _ = rag.retriever.bm25  # 첫 질문 지연을 줄이려고 미리 생성
    return rag


st.title("⚖️ 민사법 판례 Knowledge Agent")
st.caption("대법원 민사 판례·민법 조문에 근거해 답하고, 근거가 없으면 정보 부족을 안내합니다. 출처: 법제처 국가법령정보센터")

with st.sidebar:
    st.subheader("구성")
    run_config = st.radio(
        "검색 구성",
        list(RUN_CONFIGS),
        index=list(RUN_CONFIGS).index("C"),
        captions=["검색 없이 LLM 단독", "Vector", "BM25+Vector (RRF)", "Hybrid + re-ranking", "C + 쿼리 리라이트"],
    )
    st.divider()
    st.caption(f"LLM {config.LLM_MODEL} · 임베딩 {config.EMBEDDING_MODEL}")
    st.caption(f"reranker {config.RERANKER_MODEL} · 벡터 {config.VECTOR_BACKEND} · 색인 {config.INDEX_VERSION}")
    st.caption(f"후보 {config.FIRST_STAGE_K} → 최종 {config.FINAL_K} · 가중치 {config.ENSEMBLE_WEIGHTS}")

question = st.text_area(
    "질문 또는 시험 지문",
    placeholder="예) 임대인이 임차인에게 임대차보증금을 반환할 의무와 임차인의 목적물 반환 의무는 동시이행관계에 있다. (O/X)",
    height=110,
)

if st.button("질문하기", type="primary", disabled=not question.strip()):
    with st.spinner("검색하고 답변을 만드는 중…"):
        try:
            res = get_rag().ask(question.strip(), run_config)
        except FileNotFoundError as e:
            st.error(f"색인이 없습니다: {e}")
            st.stop()

    ans = res.answer
    badge = {"ok": "🟢 정상", "no_evidence": "🟡 근거 없음", "error": "🔴 오류", "timeout": "🔴 시간 초과"}[ans.status]
    c1, c2, c3 = st.columns(3)
    c1.metric("상태", badge)
    c2.metric("판단", ans.verdict or "–")
    c3.metric("응답 시간", f"{res.total_seconds:.1f}s")

    if ans.status in ("error", "timeout"):
        st.error(ans.error)
    else:
        st.markdown(ans.answer)
    if not ans.citation_valid:
        st.warning(f"검색 결과에 없는 인용 번호가 있어 제외했습니다: {sorted(set(ans.citations) - set(ans.valid_citations))}")

    ret = res.retrieval
    if ret:
        if ret.rewritten_query:
            st.info(f"변환 질의: {ret.rewritten_query}")
        elif ret.rewrite_status:
            st.caption(f"리라이트 {ret.rewrite_status} → 원질문으로 검색")
        st.subheader("근거")
        for n, c in enumerate(ret.final, 1):
            cited = n in ans.valid_citations
            with st.expander(f"{'★ ' if cited else ''}[문서 {n}] {c.cite_label()}", expanded=cited):
                st.caption(f"{c.chunk_id}")
                st.text(c.text.split("\n", 1)[-1])
        with st.expander("단계별 후보·점수"):
            st.dataframe(pd.DataFrame([{
                "chunk_id": c.chunk_id, "출처": c.cite_label(),
                "bm25": c.bm25_score, "bm25순위": c.bm25_rank,
                "vector": c.vector_score, "vector순위": c.vector_rank,
                "rrf": c.fused_score, "rrf순위": c.fused_rank,
                "rerank": c.rerank_score, "rerank순위": c.rerank_rank,
            } for c in ret.final]), use_container_width=True)
            st.json({k: round(v, 3) for k, v in ret.timings.items()})

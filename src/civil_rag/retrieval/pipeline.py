"""검색 파이프라인 A / B / C (노션 STEP 3, 교안 3·5장).

A: Vector baseline                 — 벡터 검색 상위 FINAL_K
B: Hybrid (BM25 + Vector, 가중 RRF) — 각 FIRST_STAGE_K 후보 → RRF → 상위 FINAL_K
C: Hybrid + re-ranking             — B의 결합 후보 FIRST_STAGE_K개 → CrossEncoder 재정렬 → 상위 FINAL_K
쿼리 리라이트를 켜면 변환 질의로 BM25·Vector·reranker 를 모두 실행한다 (원질문도 기록).

모든 구성은 같은 청크 집합(data/index/chunks.jsonl)을 쓴다.
"""

from __future__ import annotations

import time
from functools import cached_property

import numpy as np

from civil_rag import config
from civil_rag.ingest.build import MEMORY_STORE_FILE, load_chunks
from civil_rag.ingest.chunking import Chunk
from civil_rag.retrieval.fusion import weighted_rrf
from civil_rag.retrieval.tokenize import get_tokenizer
from civil_rag.retrieval.types import Candidate, RetrievalResult

CONFIGS = ("A", "B", "C")


class Retriever:
    def __init__(
        self,
        backend: str | None = None,
        first_stage_k: int = config.FIRST_STAGE_K,
        final_k: int = config.FINAL_K,
        weights: tuple[float, float] = config.ENSEMBLE_WEIGHTS,
        tokenizer: str = config.BM25_TOKENIZER,
    ):
        self.backend = backend or config.VECTOR_BACKEND
        self.first_stage_k = first_stage_k
        self.final_k = final_k
        self.weights = weights
        self.tokenizer_name = tokenizer
        t0 = time.perf_counter()
        self.chunks: dict[str, Chunk] = {c.chunk_id: c for c in load_chunks()}
        self.load_seconds = time.perf_counter() - t0

    # ── 1차 검색기 ─────────────────────────────────────
    @cached_property
    def bm25(self):
        """교안 5-1: BM25Retriever.from_documents(docs, preprocess_func=...)."""
        from langchain_community.retrievers import BM25Retriever
        from langchain_core.documents import Document

        docs = [Document(page_content=c.text, metadata={"chunk_id": c.chunk_id}) for c in self.chunks.values()]
        return BM25Retriever.from_documents(
            docs, preprocess_func=get_tokenizer(self.tokenizer_name), k=self.first_stage_k
        )

    @cached_property
    def vector_store(self):
        from civil_rag.models import embeddings

        if self.backend == "memory":
            from langchain_core.vectorstores import InMemoryVectorStore

            if not MEMORY_STORE_FILE.exists():
                raise FileNotFoundError("메모리 벡터 저장소가 없습니다. `civil-rag index --backend memory` 먼저 실행.")
            return InMemoryVectorStore.load(str(MEMORY_STORE_FILE), embeddings())
        from langchain_postgres import PGVector

        return PGVector(
            embeddings=embeddings(),
            collection_name=config.COLLECTION_NAME,
            connection=config.DATABASE_URL,
            use_jsonb=True,
        )

    def article_mask(self, key: str) -> np.ndarray:
        """BM25 문서 순서 기준으로, 참조조문(또는 조문 자체)이 key 인 청크만 True."""
        docs = self.bm25.docs
        return np.array([key in self.chunks[d.metadata["chunk_id"]].metadata.get("ref_articles", []) for d in docs])

    def bm25_search(self, query: str, k: int, article: str | None = None) -> list[tuple[str, float]]:
        """BM25Retriever 내부 BM25Okapi 점수를 그대로 사용 (점수 기록용). 점수 0(겹치는 단어 없음)은 제외.
        article(조문 키) 가 있으면 그 조문을 참조하는 청크 안에서만 찾는다 (교안 3-4 메타데이터 필터)."""
        retriever = self.bm25
        scores = retriever.vectorizer.get_scores(retriever.preprocess_func(query))
        if len(scores) == 0:
            return []
        if article:
            scores = np.where(self.article_mask(article), scores, 0.0)
        top = np.argsort(scores)[::-1][:k]
        return [(retriever.docs[i].metadata["chunk_id"], float(scores[i])) for i in top if scores[i] > 0]

    def vector_search(self, query: str, k: int, article: str | None = None) -> list[tuple[str, float]]:
        """반환 점수는 코사인 유사도로 통일 (pgvector는 거리 → 1-거리). article 이 있으면 메타데이터 필터."""
        kwargs = {}
        if article:
            if self.backend == "pgvector":
                kwargs["filter"] = {"ref_articles_str": {"$like": f"%|{article}|%"}}
            else:
                kwargs["filter"] = lambda doc: article in doc.metadata.get("ref_articles", [])
        pairs = self.vector_store.similarity_search_with_score(query, k=k, **kwargs)
        out = []
        for doc, score in pairs:
            cid = doc.metadata.get("chunk_id") or doc.id
            sim = 1.0 - float(score) if self.backend == "pgvector" else float(score)
            if cid in self.chunks:
                out.append((cid, sim))
        return out

    def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]:
        """교안 5-4 CrossEncoder(ko-reranker)로 질의–청크 관련도를 다시 매겨 정렬 (점수 기록)."""
        if not candidates:
            return []
        from civil_rag.models import cross_encoder

        scores = cross_encoder().score([(query, c.text) for c in candidates])
        for c, s in zip(candidates, scores):
            c.rerank_score = float(s)
        ranked = sorted(candidates, key=lambda c: -c.rerank_score)
        for r, c in enumerate(ranked, 1):
            c.rerank_rank = r
        return ranked

    # ── 구성별 실행 ────────────────────────────────────
    def _candidate(self, cid: str) -> Candidate:
        ch = self.chunks[cid]
        return Candidate(chunk_id=cid, doc_id=ch.doc_id, section=ch.section, text=ch.text, metadata=ch.metadata)

    def retrieve(self, question: str, mode: str = "C", rewrite: bool = False,
                 article: str | None = None) -> RetrievalResult:
        """article: '민법 제750조' 또는 'law:민법:750' — 주면 그 조문 관련 청크에서만 검색."""
        if mode not in CONFIGS:
            raise ValueError(f"mode 는 {CONFIGS} 중 하나")
        if article and not article.startswith("law:"):
            from civil_rag.ingest.chunking import parse_ref_articles

            keys = parse_ref_articles(article)
            if not keys:
                raise ValueError(f"조문을 알아볼 수 없습니다: {article!r} (예: '민법 제750조')")
            article = keys[0]
        timings: dict[str, float] = {}
        stages: dict[str, list[str]] = {}

        query, rewritten, rw_status = question, None, None
        if rewrite:
            from civil_rag.retrieval.rewrite import rewrite_query

            t = time.perf_counter()
            query, rw_status = rewrite_query(question)
            rewritten = query if rw_status == "ok" else None
            timings["rewrite"] = time.perf_counter() - t

        t = time.perf_counter()
        vec = self.vector_search(query, self.final_k if mode == "A" else self.first_stage_k, article)
        timings["vector"] = time.perf_counter() - t
        stages["vector"] = [cid for cid, _ in vec]
        vec_score = {cid: s for cid, s in vec}
        vec_rank = {cid: r for r, (cid, _) in enumerate(vec, 1)}

        bm_score: dict[str, float] = {}
        bm_rank: dict[str, int] = {}
        if mode in ("B", "C"):
            t = time.perf_counter()
            bm = self.bm25_search(query, self.first_stage_k, article)
            timings["bm25"] = time.perf_counter() - t
            stages["bm25"] = [cid for cid, _ in bm]
            bm_score = {cid: s for cid, s in bm}
            bm_rank = {cid: r for r, (cid, _) in enumerate(bm, 1)}

        def fill(c: Candidate) -> Candidate:
            c.vector_score, c.vector_rank = vec_score.get(c.chunk_id), vec_rank.get(c.chunk_id)
            c.bm25_score, c.bm25_rank = bm_score.get(c.chunk_id), bm_rank.get(c.chunk_id)
            return c

        if mode == "A":
            final = [fill(self._candidate(cid)) for cid, _ in vec][: self.final_k]
        else:
            fused = weighted_rrf([stages["bm25"], stages["vector"]], self.weights, c=config.RRF_C)
            pool = []
            for r, (cid, s) in enumerate(fused[: self.first_stage_k], 1):
                c = fill(self._candidate(cid))
                c.fused_score, c.fused_rank = s, r
                pool.append(c)
            stages["fused"] = [c.chunk_id for c in pool]
            if mode == "B":
                final = pool[: self.final_k]
            else:
                t = time.perf_counter()
                ranked = self.rerank(query, pool)
                timings["rerank"] = time.perf_counter() - t
                stages["reranked"] = [c.chunk_id for c in ranked]
                final = ranked[: self.final_k]

        # 근거 부족 임계값 (개발셋으로 정한 값. 기본은 꺼져 있음)
        gated = False
        thr_vec, thr_rr = config.MIN_VECTOR_SIMILARITY, config.MIN_RERANK_SCORE
        if mode == "A" and thr_vec is not None:
            kept = [c for c in final if (c.vector_score or 0) >= thr_vec]
            gated, final = (len(kept) == 0 and len(final) > 0), kept
        elif mode == "C" and thr_rr is not None:
            kept = [c for c in final if (c.rerank_score or float("-inf")) >= thr_rr]
            gated, final = (len(kept) == 0 and len(final) > 0), kept

        timings["retrieval_total"] = sum(v for k, v in timings.items())
        if article:
            stages["article_filter"] = [article]
        return RetrievalResult(
            config=mode,
            query=query,
            original_query=question,
            rewritten_query=rewritten,
            rewrite_status=rw_status,
            final=final,
            stages=stages,
            timings=timings,
            gated_out=gated,
        )

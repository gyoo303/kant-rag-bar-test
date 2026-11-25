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
from civil_rag.retrieval.tokenize import cached_tokens, get_tokenizer
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
        self.date_to = config.RETRIEVAL_DATE_TO
        t0 = time.perf_counter()
        self.chunks: dict[str, Chunk] = {c.chunk_id: c for c in load_chunks()}
        self.load_seconds = time.perf_counter() - t0

    # ── 1차 검색기 ─────────────────────────────────────
    @cached_property
    def bm25(self):
        """교안 5-1: BM25Retriever.from_documents(docs, preprocess_func=...)."""
        from langchain_community.retrievers import BM25Retriever
        from langchain_core.documents import Document

        from rank_bm25 import BM25Okapi

        docs = [Document(page_content=c.text, metadata={"chunk_id": c.chunk_id}) for c in self.chunks.values()]
        tokenized = cached_tokens(self.tokenizer_name, list(self.chunks), [c.text for c in self.chunks.values()])
        # BM25Retriever.from_documents 와 같은 구성. 토큰화 결과만 캐시에서 가져온다 (kiwi 는 전체 토큰화에 수 분)
        return BM25Retriever(vectorizer=BM25Okapi(tokenized), docs=docs,
                             preprocess_func=get_tokenizer(self.tokenizer_name), k=self.first_stage_k)

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

    @cached_property
    def _bm25_matrix(self):
        """BM25Okapi 점수를 미리 (문서 × 단어) 희소행렬로 계산해 둔다. 점수는 rank_bm25 get_scores 와 같고,
        질의마다 전체 문서를 파이썬으로 도는 대신 행렬 곱 한 번이라 빠르다 (동시 실행 시 GIL 경합도 줄어듦)."""
        from scipy.sparse import csr_matrix

        v = self.bm25.vectorizer
        vocab: dict[str, int] = {}
        rows, cols, vals = [], [], []
        k1, b, avgdl = v.k1, v.b, v.avgdl
        for i, (freqs, dl) in enumerate(zip(v.doc_freqs, v.doc_len)):
            norm = k1 * (1 - b + b * dl / avgdl)
            for term, tf in freqs.items():
                j = vocab.setdefault(term, len(vocab))
                rows.append(i)
                cols.append(j)
                vals.append(v.idf.get(term, 0.0) * tf * (k1 + 1) / (tf + norm))
        m = csr_matrix((np.asarray(vals, dtype=np.float64), (rows, cols)), shape=(len(v.doc_freqs), len(vocab)))
        return m.tocsc(), vocab

    def bm25_scores(self, query: str) -> np.ndarray:
        """rank_bm25 의 get_scores(preprocess(query)) 와 같은 값 (질의 단어 중복은 그만큼 더함)."""
        m, vocab = self._bm25_matrix
        qv = np.zeros(m.shape[1])
        for t in self.bm25.preprocess_func(query):
            j = vocab.get(t)
            if j is not None:
                qv[j] += 1.0
        if not qv.any():
            return np.zeros(m.shape[0])
        return m @ qv

    @cached_property
    def _doc_type_arr(self) -> np.ndarray:
        return np.array([self.chunks[d.metadata["chunk_id"]].doc_type for d in self.bm25.docs])

    def date_ok(self, cid: str) -> bool:
        """검색 시점 필터 (RETRIEVAL_DATE_TO). 판례는 선고일이 상한 이하일 때만, 조문은 항상 통과.
        색인을 새로 만들지 않고 더 이른 해의 시험을 풀 때 시험일 이후 판례를 빼기 위한 것."""
        if not self.date_to:
            return True
        ch = self.chunks.get(cid)
        if ch is None or ch.doc_type != "prec":
            return True
        d = "".join(x for x in str(ch.metadata.get("decision_date") or "") if x.isdigit())
        return len(d) == 8 and d <= self.date_to

    @cached_property
    def _date_mask(self) -> np.ndarray:
        return np.array([self.date_ok(d.metadata["chunk_id"]) for d in self.bm25.docs])

    def bm25_search(self, query: str, k: int, article: str | None = None,
                    doc_type: str | None = None) -> list[tuple[str, float]]:
        """BM25Retriever 내부 BM25Okapi 점수를 그대로 사용 (점수 기록용). 점수 0(겹치는 단어 없음)은 제외.
        article(조문 키) 가 있으면 그 조문을 참조하는 청크 안에서만 찾는다 (교안 3-4 메타데이터 필터)."""
        retriever = self.bm25
        scores = self.bm25_scores(query)
        if len(scores) == 0:
            return []
        if article:
            scores = np.where(self.article_mask(article), scores, 0.0)
        if doc_type:
            scores = np.where(self._doc_type_arr == doc_type, scores, 0.0)
        if self.date_to:
            scores = np.where(self._date_mask, scores, 0.0)
        top = np.argsort(scores)[::-1][:k]
        return [(retriever.docs[i].metadata["chunk_id"], float(scores[i])) for i in top if scores[i] > 0]

    def vector_search(self, query: str, k: int, article: str | None = None,
                      doc_type: str | None = None) -> list[tuple[str, float]]:
        """반환 점수는 코사인 유사도로 통일 (pgvector는 거리 → 1-거리).
        article(참조조문)·doc_type(prec|law) 이 있으면 메타데이터 필터."""
        kwargs = {}
        if article or doc_type:
            if self.backend == "pgvector":
                conds = []
                if article:
                    conds.append({"ref_articles_str": {"$like": f"%|{article}|%"}})
                if doc_type:
                    conds.append({"doc_type": {"$eq": doc_type}})
                kwargs["filter"] = conds[0] if len(conds) == 1 else {"$and": conds}
            else:
                kwargs["filter"] = lambda doc: ((not article or article in doc.metadata.get("ref_articles", []))
                                                and (not doc_type or doc.metadata.get("doc_type") == doc_type))
        # 시점 필터가 있으면 넉넉히 받아서 시험일 이후 판례를 뺀 뒤 k개로 자른다
        fetch = k * 2 if self.date_to else k
        pairs = self.vector_store.similarity_search_with_score(query, k=fetch, **kwargs)
        out = []
        for doc, score in pairs:
            cid = doc.metadata.get("chunk_id") or doc.id
            sim = 1.0 - float(score) if self.backend == "pgvector" else float(score)
            if cid in self.chunks and self.date_ok(cid):
                out.append((cid, sim))
        return out[:k]

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
                 article: str | None = None, doc_type: str | None = None) -> RetrievalResult:
        """article: '민법 제750조' 또는 'law:민법:750' — 주면 그 조문 관련 청크에서만 검색.
        doc_type: 'law' | 'prec' — 주면 그 종류 청크에서만 검색 (조문 몫 보장용)."""
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
        vec = self.vector_search(query, self.final_k if mode == "A" else self.first_stage_k, article, doc_type)
        timings["vector"] = time.perf_counter() - t
        stages["vector"] = [cid for cid, _ in vec]
        vec_score = {cid: s for cid, s in vec}
        vec_rank = {cid: r for r, (cid, _) in enumerate(vec, 1)}

        bm_score: dict[str, float] = {}
        bm_rank: dict[str, int] = {}
        if mode in ("B", "C"):
            t = time.perf_counter()
            bm = self.bm25_search(query, self.first_stage_k, article, doc_type)
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
        if doc_type:
            stages["doc_type_filter"] = [doc_type]
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

"""검색 구성 A/B/C.

A (vector)        : 벡터 검색만
B (hybrid)        : BM25 + Vector → RRF
C (hybrid_rerank) : B 의 후보 fused_k 개 → reranker → final_k
"""

from __future__ import annotations

from enum import Enum

from kant_rag.config import Settings
from kant_rag.ingest.build_index import load_chunks
from kant_rag.retrieval.bm25 import BM25Index
from kant_rag.retrieval.hybrid import rrf_fuse
from kant_rag.retrieval.rerank import Reranker
from kant_rag.retrieval.vector import VectorIndex
from kant_rag.schemas import RetrievedChunk


class RetrievalMode(str, Enum):
    A = "vector"
    B = "hybrid"
    C = "hybrid_rerank"


class Retriever:
    def __init__(self, settings: Settings):
        self.s = settings
        index_dir = settings.resolve(settings.paths.index_dir)
        chunks = load_chunks(settings)
        self.bm25 = BM25Index.load(index_dir / "bm25.pkl")
        self.vector = VectorIndex.load(index_dir / "faiss", settings.models.embedding_model, chunks)
        self.reranker = Reranker(settings.models.reranker_model)

    def retrieve(self, query: str, mode: RetrievalMode) -> dict[str, list[RetrievedChunk]]:
        """최종 결과(`final`)와 단계별 후보를 모두 반환합니다 (실행 기록용)."""
        r = self.s.retrieval
        vec = self.vector.search(query, r.vector_k)
        if mode == RetrievalMode.A:
            return {"vector": vec, "final": vec[: r.final_k]}

        bm = self.bm25.search(query, r.bm25_k)
        fused = rrf_fuse({"vector": vec, "bm25": bm}, rrf_k=r.rrf_k, top_k=r.fused_k)
        if mode == RetrievalMode.B:
            return {"vector": vec, "bm25": bm, "fused": fused, "final": fused[: r.final_k]}

        reranked = self.reranker.rerank(query, fused, top_k=r.final_k)
        return {"vector": vec, "bm25": bm, "fused": fused, "final": reranked}

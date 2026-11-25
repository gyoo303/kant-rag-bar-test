"""검색 구성 A/B/C.

A (vector)        : 벡터 검색만
B (hybrid)        : BM25 + Vector → RRF
C (hybrid_rerank) : B 의 후보 fused_k 개 → reranker → final_k
"""

from __future__ import annotations

import json
import re
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
    NONE = "closed_book"  # 기준선: 검색 없이 모델 지식만 (선택형 풀이 전용)


class Retriever:
    def __init__(self, settings: Settings):
        self.s = settings
        index_dir = settings.index_path()
        missing = [p for p in ("chunks.jsonl", "bm25.pkl", "faiss/index.faiss", "index_info.json")
                   if not (index_dir / p).exists()]
        if missing:
            raise SystemExit(f"색인이 없거나 미완성입니다 (없음: {', '.join(missing)}).\n"
                             "→ `uv run kant-rag build-index` 를 끝까지 실행한 뒤 다시 시도하세요.")
        info = json.loads((index_dir / "index_info.json").read_text(encoding="utf-8"))
        if info.get("embedding_model") != settings.models.embedding_model:
            raise SystemExit(f"색인은 임베딩 '{info.get('embedding_model')}' 로 만들어졌는데 지금 설정은 "
                             f"'{settings.models.embedding_model}' 입니다.\n→ 같은 EMBEDDING_MODEL 로 build-index 를 다시 실행하세요.")
        chunks = load_chunks(settings)
        self.bm25 = BM25Index.load(index_dir / "bm25.pkl")
        e = settings.embedding
        self.vector = VectorIndex.load(index_dir / "faiss", settings.models.embedding_model, chunks, e)
        self.reranker = Reranker(settings.models.reranker_model, e.max_tokens, e.batch_size, e.fp16)

    def _date_filter(self, results: list[RetrievedChunk], k: int, cutoff=None) -> list[RetrievedChunk]:
        """cutoff(기본 retrieval.case_date_to) 이후 선고된 판례 청크를 빼고 순위를 다시 매김 (조문은 그대로)."""
        cutoff = cutoff or self.s.retrieval.case_date_to
        if not cutoff:
            return results[:k]
        cutoff = re.sub(r"\D", "", str(cutoff))
        kept = []
        for x in results:
            decided = re.sub(r"\D", "", str(x.chunk.metadata.get("decided") or ""))
            if x.chunk.metadata.get("doc_type") == "case" and decided and decided > cutoff:
                continue
            kept.append(x.model_copy(update={"rank": len(kept) + 1}))
        return kept[:k]

    def retrieve(self, query: str, mode: RetrievalMode, date_to: str | None = None) -> dict[str, list[RetrievedChunk]]:
        """최종 결과(`final`)와 단계별 후보를 모두 반환합니다 (실행 기록용).
        date_to: 이 문항에만 적용할 판례 선고일 상한 (발문 기준 시점, v5)."""
        if mode == RetrievalMode.NONE:
            raise ValueError("closed_book 은 검색을 하지 않는 기준선입니다 (선택형 풀이 전용)")
        r = self.s.retrieval
        cutoff = min(filter(None, [str(date_to) if date_to else None,
                                   str(r.case_date_to) if r.case_date_to else None]), default=None)
        extra = 2 if cutoff else 1  # 날짜 필터로 빠질 후보를 감안해 더 넉넉히 받음
        vec = self._date_filter(self.vector.search(query, r.vector_k * extra), r.vector_k, cutoff)
        if mode == RetrievalMode.A:
            return {"vector": vec, "final": vec[: r.final_k]}

        bm = self._date_filter(self.bm25.search(query, r.bm25_k * extra), r.bm25_k, cutoff)
        fused = rrf_fuse({"vector": vec, "bm25": bm}, rrf_k=r.rrf_k, top_k=r.fused_k)
        if mode == RetrievalMode.B:
            return {"vector": vec, "bm25": bm, "fused": fused, "final": fused[: r.final_k]}

        reranked = self.reranker.rerank(query, fused, top_k=r.final_k)
        return {"vector": vec, "bm25": bm, "fused": fused, "final": reranked}

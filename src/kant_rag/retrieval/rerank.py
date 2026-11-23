"""Cross-encoder re-ranking: (질의, 청크) 쌍의 관련도를 다시 계산해 재정렬합니다."""

from __future__ import annotations

from functools import lru_cache

from kant_rag.schemas import RetrievedChunk


@lru_cache
def _cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


class Reranker:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        if not candidates:
            return []
        model = _cross_encoder(self.model_name)
        # bge-reranker 계열은 sigmoid 를 적용해 0~1 관련도로 사용 (사실성 확률이 아님!)
        import torch

        scores = model.predict(
            [(query, c.chunk.text) for c in candidates], activation_fn=torch.nn.Sigmoid()
        )
        paired = sorted(zip(candidates, scores, strict=True), key=lambda x: -float(x[1]))
        out = []
        for rank, (c, s) in enumerate(paired[:top_k], start=1):
            trace = dict(c.trace)
            trace.update({"pre_rerank_rank": c.rank, "rerank_score": float(s), "rerank_rank": rank})
            out.append(RetrievedChunk(chunk=c.chunk, score=float(s), rank=rank, source="rerank", trace=trace))
        return out

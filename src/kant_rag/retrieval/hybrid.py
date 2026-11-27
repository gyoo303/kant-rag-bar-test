"""BM25 + Vector 결합: Reciprocal Rank Fusion.

BM25 점수(비유계)와 코사인 유사도(-1~1)는 척도가 달라 단순 합산하지 않습니다.
RRF 는 점수 대신 순위만 사용합니다:  score(d) = Σ_r  w_r / (rrf_k + rank_r(d))
중복 제거: chunk_id 기준으로 하나로 합치고, 각 검색기의 원 순위/점수는 trace 에 보존합니다.
"""

from __future__ import annotations

from kant_rag.schemas import RetrievedChunk


def rrf_fuse(
    result_lists: dict[str, list[RetrievedChunk]],
    rrf_k: int = 60,
    top_k: int = 20,
    weights: dict[str, float] | None = None,
) -> list[RetrievedChunk]:
    weights = weights or {}
    fused: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for name, results in result_lists.items():
        w = weights.get(name, 1.0)
        for r in results:
            cid = r.chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + w / (rrf_k + r.rank)
            if cid not in fused:
                fused[cid] = RetrievedChunk(chunk=r.chunk, score=0.0, rank=0, source="rrf", trace={})
            fused[cid].trace.update(r.trace)
    ordered = sorted(fused, key=lambda c: (-scores[c], c))  # 동점은 chunk_id 로 결정적 정렬
    out = []
    for rank, cid in enumerate(ordered[:top_k], start=1):
        item = fused[cid]
        item.score = scores[cid]
        item.rank = rank
        item.trace.update({"rrf_score": scores[cid], "rrf_rank": rank})
        out.append(item)
    return out

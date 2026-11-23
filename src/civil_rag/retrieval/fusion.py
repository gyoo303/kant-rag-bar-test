"""하이브리드 결합: 가중 RRF (교안 5-3).

score(d) = Σ_i  w_i / (c + rank_i(d))      c = 60, rank는 1부터
langchain_classic EnsembleRetriever.weighted_reciprocal_rank 와 같은 식이다.
EnsembleRetriever는 점수를 돌려주지 않아서, 노션 요구(후보·점수·중복 제거 규칙 기록)를 위해 같은 식을 직접 계산한다.
중복 제거: chunk_id 기준 (EnsembleRetriever 기본값은 page_content 기준).
"""

from __future__ import annotations

from collections.abc import Sequence


def weighted_rrf(
    ranked_lists: Sequence[Sequence[str]],
    weights: Sequence[float],
    c: int = 60,
) -> list[tuple[str, float]]:
    """chunk_id 순위 목록들 → [(chunk_id, 결합 점수)] 내림차순. 동점이면 먼저 나온 목록·순위 우선."""
    if len(ranked_lists) != len(weights):
        raise ValueError("ranked_lists 와 weights 길이가 다릅니다.")
    scores: dict[str, float] = {}
    first_seen: dict[str, tuple[int, int]] = {}
    for li, (ids, w) in enumerate(zip(ranked_lists, weights)):
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + w / (c + rank)
            first_seen.setdefault(cid, (rank, li))
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))

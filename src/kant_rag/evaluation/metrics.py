"""자동 계산 지표: Hit@5, 호출 성공률, 응답 시간.
정답 충족·근거 적합·정보 부족 안내는 사람이 채점(grading CSV)하고 aggregate 에서 합산합니다.
"""

from __future__ import annotations

import statistics

from kant_rag.evaluation.dataset import EvalItem


def hit_at_k(record: dict, item: EvalItem, k: int = 5) -> int:
    """허용 근거 청크가 최종 상위 k 안에 하나라도 있으면 1. 검색 실패는 0."""
    final = (record.get("retrieval") or {}).get("final") or []
    allowed = {e.chunk_id for e in item.evidence}
    return int(any(r["chunk_id"] in allowed for r in final[:k]))


def latency_summary(records: list[dict]) -> dict:
    ok = [r["timing_ms"]["total"] for r in records
          if r["answer"]["status"] not in ("retrieval_error", "generation_error")]
    return {
        "n_success": len(ok),
        "n_total": len(records),
        "n_error": len(records) - len(ok),
        "mean_ms": round(statistics.mean(ok), 1) if ok else None,
        "median_ms": round(statistics.median(ok), 1) if ok else None,
    }


def retrieval_summary(records: list[dict], items: dict[str, EvalItem], k: int = 5) -> dict:
    answerable = [r for r in records if items[r["question_id"]].type != "no_answer"]
    hits = sum(hit_at_k(r, items[r["question_id"]], k) for r in answerable)
    return {f"hit@{k}": f"{hits}/{len(answerable)}",
            f"hit@{k}_rate": round(hits / len(answerable), 3) if answerable else None}

"""채점 지표 (노션 STEP 6). 자동 채점은 예비값이고, 정답 충족·근거 적합은 팀원 교차 검토로 확정한다."""

from __future__ import annotations

import statistics
from collections.abc import Iterable

OX = {"O", "X"}
FAILED = {"error", "timeout"}


def evidence_match(cand: dict, ev: dict) -> bool:
    """허용 근거 1개와 검색 결과 1개가 같은지.
    우선순위: chunk_id 일치 → (doc_id, section) 일치 → doc_id 일치 → 사건번호 일치."""
    meta = cand.get("metadata", {})
    if ev.get("chunk_id"):
        return cand.get("chunk_id") == ev["chunk_id"]
    if ev.get("doc_id"):
        if str(cand.get("doc_id")) != str(ev["doc_id"]):
            return False
        return not ev.get("section") or cand.get("section") == ev["section"]
    if ev.get("case_no"):
        if meta.get("case_no") != ev["case_no"]:
            return False
        return not ev.get("section") or cand.get("section") == ev["section"]
    return False


def hit_at_k(final: list[dict], allowed: list[dict], k: int = 5) -> int:
    """허용 근거가 상위 k개 안에 하나라도 있으면 1. 검색 실패(빈 결과)는 0."""
    top = final[:k]
    return int(any(evidence_match(c, ev) for c in top for ev in allowed))


def verdict_correct(expected_answer: str | None, verdict: str | None, status: str) -> int | None:
    """OX 문항 자동 판정. 서술형이면 None(수동 채점)."""
    if (expected_answer or "").strip() not in OX:
        return None
    if status in FAILED:
        return 0
    return int(verdict == expected_answer.strip())


def no_evidence_correct(verdict: str | None, status: str) -> int:
    """근거 없음 문항: 정보 부족을 안내했으면 1. 호출 오류는 올바른 거절로 세지 않는다."""
    return int(status not in FAILED and verdict == "정보 부족")


def citation_auto(answer: dict) -> int:
    """근거 적합 자동 예비값: 인용이 1개 이상이고 모두 실제 검색 결과 안의 번호면 1."""
    return int(answer.get("status") == "ok" and bool(answer.get("valid_citations")) and bool(answer.get("citation_valid")))


def latency_stats(seconds: Iterable[float]) -> dict:
    xs = list(seconds)
    if not xs:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(xs), "mean": round(statistics.mean(xs), 2), "median": round(statistics.median(xs), 2)}


def summarize(rows: list[dict], has_retrieval: bool) -> dict:
    """rows: 채점된 문항 행들 (같은 구성). 분모를 모두 함께 돌려준다."""
    ans = [r for r in rows if r["type"] != "no_evidence"]
    ne = [r for r in rows if r["type"] == "no_evidence"]
    ox = [r for r in ans if r["verdict_auto"] is not None]
    ok_rows = [r for r in rows if r["status"] not in FAILED]
    out = {
        "attempts": len(rows),
        "success": len(ok_rows),
        "errors": sum(r["status"] == "error" for r in rows),
        "timeouts": sum(r["status"] == "timeout" for r in rows),
        "answerable": len(ans),
        "hit_at_5": (sum(r["hit_at_5"] or 0 for r in ans), len(ans)) if has_retrieval else None,
        "verdict_auto": (sum(r["verdict_auto"] for r in ox), len(ox)),
        "citation_auto": (sum(r["citation_auto"] for r in ans), len(ans)) if has_retrieval else None,
        "no_evidence": (sum(r["no_evidence_ok"] for r in ne), len(ne)),
        "latency": latency_stats(r["seconds"] for r in ok_rows),
    }
    return out


def fmt_ratio(pair: tuple[int, int] | None) -> str:
    if pair is None:
        return "–"
    num, den = pair
    return f"{num}/{den}" + (f" ({num / den:.2f})" if den else "")

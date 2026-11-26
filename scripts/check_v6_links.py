"""v6 오프라인 확인: 색인 없이 원자료로 청크를 만들어, 알려진 오답의 결정적 근거가 v6 연결로 닿는지 본다.

  uv run python scripts/check_v6_links.py
LLM·GPU 를 쓰지 않는다. 리랭커 대신 '후보에 들어가는가'까지만 확인 (실제 선택은 리랭커 점수에 달림).
"""
from __future__ import annotations

import json

from kant_rag.config import get_settings
from kant_rag.ingest.build_index import build_chunks
from kant_rag.mcq.context import (
    ChunkGraph,
    build_title_index,
    chapter_company,
    company_type,
    title_matches,
)
from kant_rag.mcq.links import LinkGraph


def main():
    s = get_settings()
    chunks = {c.chunk_id: c for c in build_chunks(s)}
    g = ChunkGraph(chunks)
    lg = LinkGraph(chunks, s.raw_path("cases"), cache=None)
    idx = build_title_index(chunks)
    out = {"chunks": len(chunks)}

    # bar12 문 40 ㅁ: 상법 제208조(합명회사) → 제389조 ③ 준용 (M1·2-4·M2)
    st = "주식회사에서 공동대표이사가 선임된 경우 거래상대방이 그 주식회사에 대하여 하는 의사표시는 그 주식회사의 공동대표이사 중 1인에게 하여도 그 효력이 있다."
    users = g.statute_users(["LAW-COMM#제208조"])
    out["bar12_40"] = {
        "statute_users(제208조)": users,
        "chapter(제208조)": chapter_company(chunks["LAW-COMM#제208조"]), "statement_type": company_type(st),
        "chapter_user": [u for u in users if chapter_company(chunks[u]) == company_type(st)],
        "title_matches": title_matches(st, idx),
    }
    # bar12 문 69 · bar13 문 23: 판례 변경 표시
    out["bar12_69"] = lg.overruled_info("99다23888")
    out["bar13_23"] = lg.overruled_info("2008스67")
    # bar13 문 38: 민법 제481·482·368조 → 2014다51756 (2-2 조문 → 판례)
    res = {}
    for art in ("제481조", "제482조", "제368조"):
        cid = next((x for x in chunks if x.startswith(f"LAW-CIVIL#{art}")), None)
        cands = lg.candidates([cid], max_n=10_000) if cid else []
        pos = [i for i, (x, _) in enumerate(cands) if "2014다51756" in x]
        res[art] = {"candidates": len(cands), "rank_of_2014다51756": pos[0] + 1 if pos else None}
    out["bar13_38"] = res
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

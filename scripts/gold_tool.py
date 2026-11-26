"""정답 근거 라벨링 도구 (verify-2022 코퍼스: 2022. 1. 10. 판례 + 2022. 1. 1. 법령). GPU·LLM 불필요.

  uv run python scripts/gold_tool.py brief 1-10          # 문항·지문·정답 라벨(참/거짓)
  uv run python scripts/gold_tool.py search "질의" [--k 10] [--type statute|case]
  uv run python scripts/gold_tool.py show CHUNK_ID [CHUNK_ID ...]
  uv run python scripts/gold_tool.py article 민법 제750조   # 조문 청크 id 찾기
  uv run python scripts/gold_tool.py case 2019다12345      # 판례 항목 청크 ids

처음 실행 때 청크·BM25 를 만들어 캐시 (KANT_GOLD_CACHE, 기본 scratch 대신 .cache/gold_2022.pkl).
"""
from __future__ import annotations

import argparse
import os
import pickle
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.getenv("KANT_GOLD_CACHE", ROOT / ".cache" / "gold_2022.pkl"))


def _load():
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    from kant_rag.config import get_settings
    from kant_rag.ingest.build_index import build_chunks
    from kant_rag.retrieval.bm25 import BM25Index

    s = get_settings(str(ROOT / "configs" / "default.yaml"))
    chunks = build_chunks(s)
    data = {"by_id": {c.chunk_id: c for c in chunks}, "bm25": BM25Index.build(chunks, s.retrieval.bm25_tokenizer)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    return data


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief"); b.add_argument("range")
    se = sub.add_parser("search"); se.add_argument("query"); se.add_argument("--k", type=int, default=10)
    se.add_argument("--type", default=None)
    sh = sub.add_parser("show"); sh.add_argument("ids", nargs="+")
    ar = sub.add_parser("article"); ar.add_argument("law"); ar.add_argument("art")
    ca = sub.add_parser("case"); ca.add_argument("case_no")
    a = ap.parse_args()

    if a.cmd == "brief":
        from kant_rag.mcq.io import load_bar_evalset
        lo, hi = (int(x) for x in a.range.split("-"))
        for q in load_bar_evalset(ROOT / "data" / "exam" / "bar11_civil.json").items:
            if not lo <= q.number <= hi:
                continue
            print(f"\n=== 문 {q.number} [{q.subject}·{q.form}·{q.polarity}] 정답 {q.answer}\n{q.stem}")
            for k, v in q.statements().items():
                lab = q.statement_labels.get(k)
                print(f"  [{k}] ({'참' if lab else '거짓' if lab is not None else '?'}) {v}")
            if q.form not in ("single",):
                print("  보기:", q.options)
        return

    d = _load()
    by_id = d["by_id"]
    if a.cmd == "search":
        k = a.k * (4 if a.type else 1)
        rs = d["bm25"].search(a.query, k)
        n = 0
        for r in rs:
            c = r.chunk
            if a.type and (c.metadata or {}).get("doc_type") != a.type:
                continue
            body = c.text.replace("\n", " ")
            print(f"- {c.chunk_id} | {body[:260]}")
            n += 1
            if n >= a.k:
                break
    elif a.cmd == "show":
        for x in a.ids:
            c = by_id.get(x)
            print(f"\n##### {x}\n{c.text if c else '(없음)'}")
    elif a.cmd == "article":
        law = re.sub(r"\s", "", a.law)
        for cid, c in by_id.items():
            md = c.metadata or {}
            if md.get("doc_type") == "statute" and re.sub(r"\s", "", c.title) == law and \
                    str(md.get("article", "")).split("~")[0] == a.art:
                print(f"- {cid} | {c.text[:200].replace(chr(10), ' ')}")
    elif a.cmd == "case":
        for cid, c in by_id.items():
            if (c.metadata or {}).get("case_no", "").startswith(a.case_no):
                print(f"- {cid} | {c.text[:200].replace(chr(10), ' ')}")


if __name__ == "__main__":
    sys.exit(main())

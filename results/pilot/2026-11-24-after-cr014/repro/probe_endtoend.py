"""실제 문항을 파이프라인 끝까지 N번 돌려 무엇이 흔들리는지 본다.

LLM 호출이 둘이다: 쿼리 리라이터와 생성기. 둘 다 비결정적일 수 있다.
"""
import json, sys
from collections import Counter
from lawqa.entrypoints.composition import build_answer_runtime
from lawqa.shared.db import connect
from lawqa.shared.settings import load_settings

N = 5
NOS = [9, 2]  # 9: 실행마다 뒤집힌 조합형 / 2: 안정적이던 일반형
items = {i["no"]: i for i in json.load(open("results/pilot/2026-11-24-after-cr014/items.json", encoding="utf-8"))}

s = load_settings("base")
url = s.secrets.require("database_url")
with connect(url) as conn:
    rt = build_answer_runtime(conn, url, settings=s)
    for no in NOS:
        it = items[no]
        picks, sufs, queries, ctxs = [], [], [], []
        for _ in range(N):
            env = rt.service.answer({"stem": it["stem"], "options": it["options"]}, "C+R")
            d = env.to_dict()
            picks.append(d["answer_no"])
            sufs.append(d["evidence_sufficient"])
            queries.append(tuple(q.get("rewritten") for q in d["queries"]))
            ctxs.append(tuple(sorted(c["chunk_id"] for c in d["context"])))
        print(f"문 {no}:")
        print(f"  고른 번호      {picks}  -> 서로 다른 값 {len(set(picks))}가지")
        print(f"  근거 충족      {sufs}")
        print(f"  리라이트 질의  서로 다른 조합 {len(set(queries))}가지 / {N}회")
        print(f"  검색 컨텍스트  서로 다른 조합 {len(set(ctxs))}가지 / {N}회")
        sys.stdout.flush()

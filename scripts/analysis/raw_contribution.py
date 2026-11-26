"""원자료 구조 기여 측정: 결정 문장이 한 청크 안에 있는가 · 지문-결정 문장 겹침 · BM25 단독 Hit@5 (gold_tool 캐시 사용).
  uv run python scripts/analysis/raw_contribution.py   (먼저 scripts/gold_tool.py 를 한 번 실행해 .cache/gold_2022.pkl 생성)
"""
import json, pickle, re, sys, statistics
from pathlib import Path
from collections import Counter, defaultdict
from difflib import SequenceMatcher
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold30_metrics import ref_key, chunk_key
from kant_rag.mcq.io import load_bar_evalset

d = pickle.loads(Path(".cache/gold_2022.pkl").read_bytes())
by_id, bm = d["by_id"], d["bm25"]
key_chunks = defaultdict(list)
for cid in by_id: key_chunks[chunk_key(cid)].append(cid)
sq = lambda s: re.sub(r"[\s\"'“”‘’「」｢｣.,·ㆍ()\[\]<>]", "", s or "")
def analyze(goldfile, examfile, srcfilter=None):
    g = json.load(open(goldfile, encoding="utf-8"))
    ex = {q.number: q for q in load_bar_evalset(Path(examfile)).items}
    out = Counter(); sims = []; bmhit = []; bmhit_case = []; rows=[]
    for q in g:
        st = ex[q["number"]].statements()
        for s in q["statements"]:
            if srcfilter and not srcfilter(s.get("source","원본")): continue
            text = st[s["statement"]]
            G = {ref_key(r["ref"]) for r in s["refs"]}
            # (1) 결정 문장이 한 청크 안에
            for r in s["refs"]:
                k = ref_key(r["ref"]); qt = sq(r["quote"])[:120]
                out["refs"] += 1
                if k not in key_chunks: out["ref_not_in_corpus"] += 1; continue
                if len(qt) >= 10 and any(qt in sq(by_id[c].text) for c in key_chunks[k]): out["quote_in_one_chunk"] += 1
                elif len(qt) >= 10: out["quote_split_or_paraphrase"] += 1
            # (2) 지문 ↔ 결정 문장 겹침 (지문 글자 중 결정 문장과 3글자 이상 겹치는 비율)
            best = 0
            for r in s["refs"]:
                a, b = sq(text), sq(r["quote"])
                if not a or not b: continue
                m = sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if x.size >= 3)
                best = max(best, m / len(a))
            sims.append(best)
            # (3) BM25 단독 Hit@5 (지문만 질의)
            res = [chunk_key(x.chunk.chunk_id) for x in bm.search(text, 5)]
            bmhit.append(bool(G & set(res)))
            rows.append((q["number"], s["statement"], round(best,2), bool(G & set(res))))
    return out, sims, bmhit, rows
for name, gf, ef, f in [("원본 30", "eval/2022-validation/gold30_refs.json", "data/exam/bar11_gold30.json", None),
                        ("변형-원본지문", "eval/2022-validation/gold30_v2var_refs.json", "data/exam/bar11_gold30_v2.json", lambda s: s.startswith("원본") and "변경" not in s),
                        ("변형-새지문", "eval/2022-validation/gold30_v2var_refs.json", "data/exam/bar11_gold30_v2.json", lambda s: not (s.startswith("원본") and "변경" not in s))]:
    out, sims, bmhit, rows = analyze(gf, ef, f)
    n = len(sims)
    print(name, "지문", n, dict(out))
    print("  지문-결정문장 겹침 평균 %.2f 중앙 %.2f  ≥0.5: %d/%d  ≥0.7: %d/%d" % (statistics.mean(sims), statistics.median(sims), sum(x>=0.5 for x in sims), n, sum(x>=0.7 for x in sims), n))
    print("  BM25 단독(지문만) Hit@5: %d/%d = %.1f%%" % (sum(bmhit), n, 100*sum(bmhit)/n))
# 코퍼스 구조
cases=[c for c in by_id.values() if c.metadata.get("doc_type")=="case"]; sts=[c for c in by_id.values() if c.metadata.get("doc_type")=="statute"]
print("청크", len(by_id), "판례", len(cases), "조문", len(sts), "판례 평균 길이", int(statistics.mean(len(c.text) for c in cases)), "조문 평균", int(statistics.mean(len(c.text) for c in sts)))
print("판시사항 있는 판례 청크 비율 %.1f%%" % (100*sum("판시사항:" in c.text for c in cases)/len(cases)), "참조조문 붙은 비율 %.1f%%" % (100*sum("참조조문:" in c.text for c in cases)/len(cases)))
print("조각(~k) 판례 청크 비율 %.1f%%" % (100*sum("~" in c.chunk_id for c in cases)/len(cases)))

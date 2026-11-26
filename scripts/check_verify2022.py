"""verify-2022 오프라인 검증: 설정대로 만든 청크가 2022 시점 자료만 담는지, 법령 스냅숏이 시험에 실제로 영향을 주는지.

  uv run python scripts/check_verify2022.py
GPU·LLM 없이 실행 (벡터 색인 대신 BM25 로 진술별 검색).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from kant_rag.config import get_settings
from kant_rag.ingest.build_index import build_chunks
from kant_rag.ingest.statute import chunk_statute
from kant_rag.mcq.io import load_bar_evalset
from kant_rag.mcq.links import LinkGraph
from kant_rag.retrieval.bm25 import BM25Index
from kant_rag.schemas import DocumentMeta


def _norm(t: str) -> str:
    return re.sub(r"\s", "", re.sub(r"<[^>]*>|\[[^\]]*(개정|신설|본조|전문|시행일|제목)[^\]]*\]", "", t))


def _articles(text: str, title: str) -> dict[str, str]:
    m = DocumentMeta(doc_id="X", title=title, source="s", license="l", version="v", path="p", doc_type="statute")
    out: dict[str, str] = {}
    for c in chunk_statute(text, m):
        out[c.metadata["article"]] = out.get(c.metadata["article"], "") + _norm("".join(c.text.split("\n")[1:]))
    return out


def main():
    s = get_settings()
    snap, cutoff = str(s.corpus.statute_snapshot), str(s.corpus.case_date_to)
    rep: dict = {"settings": {"index": str(s.index_path().name), "statute_snapshot": snap, "case_date_to": cutoff,
                              "retrieval.case_date_to": s.retrieval.case_date_to, "mcq.asof_default": s.mcq.asof_default,
                              "mcq.hide_future": s.mcq.hide_future}}
    chunks = build_chunks(s)
    by_id = {c.chunk_id: c for c in chunks}
    statutes = [c for c in chunks if c.metadata.get("doc_type") == "statute"]
    cases = [c for c in chunks if c.metadata.get("doc_type") == "case"]
    rep["chunks"] = {"total": len(chunks), "statute": len(statutes), "case": len(cases),
                     "snapshot_fallback": build_chunks.snapshot_fallback, "missing": build_chunks.missing}

    # 1) 판례: 기준일 뒤 선고가 하나도 없는가
    late = [c.chunk_id for c in cases if re.sub(r"\D", "", str(c.metadata.get("decided"))) > cutoff]
    rep["cases"] = {"latest_decided": max(str(c.metadata["decided"]) for c in cases), "after_cutoff": len(late)}

    # 2) 법령: 색인 조문 = 스냅숏 파일 조문 (현재 버전이 섞이지 않았는가)
    snap_dir = s.raw_path("statutes/x.txt").parent
    cur_dir = s.resolve(s.paths.raw_dir) / "statutes"
    by_law: dict[str, dict[str, str]] = {}
    for c in statutes:
        by_law.setdefault(c.title, {})
        a = c.metadata["article"]
        by_law[c.title][a] = by_law[c.title].get(a, "") + _norm("".join(c.text.split("\n")[1:]))
    laws, changed = {}, {}
    for f in sorted(snap_dir.glob("*.txt")):
        snap_a = _articles(f.read_text(encoding="utf-8"), f.stem)
        idx_a = by_law.get(f.stem, {})
        cur = cur_dir / f.name
        cur_a = _articles(cur.read_text(encoding="utf-8"), f.stem) if cur.exists() else {}
        diff = sorted(k for k in snap_a if k in cur_a and snap_a[k] != cur_a[k])
        laws[f.stem] = {"version": next((c.metadata["version"] for c in statutes if c.title == f.stem), None),
                        "articles": len(idx_a), "same_as_snapshot": idx_a == snap_a,
                        "changed_vs_current": len(diff), "new_after_2022_excluded": sorted(set(cur_a) - set(snap_a))}
        changed[f.stem] = set(diff)
    rep["statutes"] = laws

    # 3) 판례 연결: 2022 뒤 판례가 연결·표시에 나오지 않는가
    lg = LinkGraph(by_id, s.raw_path("cases"), cache=None)
    leaks = sorted({n for c in cases for n, d in lg.overruled_info(str(c.metadata.get("case_no"))).get("overruled_by", [])
                    if d > cutoff})
    rep["links"] = {"overruled_by_after_cutoff(숨김 대상)": len(leaks),
                    "candidate_after_cutoff": sum(
                        1 for c in statutes[:3000] for x, _ in lg.candidates([c.chunk_id], cutoff=cutoff)
                        if lg.decided.get(lg.case_no_of(x)[0] if lg.case_no_of(x) else "", "") > cutoff)}

    # 4) 시험 영향: 진술별 BM25 top-5 에 '2022 이후 내용이 바뀐 조문'이 걸리는 문항
    bm = BM25Index.build(chunks, s.retrieval.bm25_tokenizer)
    es = load_bar_evalset(Path("data/exam/bar11_civil.json"))
    hit: dict[int, list[str]] = {}
    for q in es.items:
        for k, st in q.statements().items():
            for r in bm.search(st, 5):
                c = r.chunk
                if c.metadata.get("doc_type") == "statute" and c.metadata["article"] in changed.get(c.title, set()):
                    hit.setdefault(q.number, []).append(f"{k}:{c.title} {c.metadata['article']}")
    rep["exam_impact"] = {"questions": len(hit), "detail": {n: sorted(set(v)) for n, v in sorted(hit.items())}}
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=list))


if __name__ == "__main__":
    main()

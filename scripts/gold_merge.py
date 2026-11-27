"""정답 근거 라벨(JSON) → 문항 파일 evidence(지문 단위) + 검토용 CSV.

  uv run python scripts/gold_merge.py <라벨 JSON 폴더> [--exam data/exam/bar11_civil.json] [--csv data/exam/bar11_gold.csv]

라벨 JSON: [{"number", "statement", "label", "found", "evidence": [{"chunk_id", "grade"}], "note", "label_doubt"}]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label_dir")
    ap.add_argument("--exam", default="data/exam/bar11_civil.json")
    ap.add_argument("--csv", default="data/exam/bar11_gold.csv")
    a = ap.parse_args()

    from kant_rag.evaluation.dataset import EvidenceRef
    from kant_rag.mcq.io import Exam

    sys.path.insert(0, str(ROOT / "scripts"))
    from gold_tool import _load

    by_id = _load()["by_id"]
    rows = [r for f in sorted(Path(a.label_dir).glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    exam_path = ROOT / a.exam
    exam = Exam.model_validate_json(exam_path.read_text(encoding="utf-8"))
    qs = {q.number: q for q in exam.items}
    seen, problems = set(), []
    by_q: dict[int, list[EvidenceRef]] = {}
    for r in rows:
        n, k = int(r["number"]), str(r["statement"])
        q = qs.get(n)
        if q is None or k not in q.statements():
            problems.append(f"없는 지문: {n} {k}")
            continue
        if (n, k) in seen:
            problems.append(f"중복: {n} {k}")
        seen.add((n, k))
        if q.statement_labels.get(k) is not None and bool(r["label"]) != q.statement_labels[k]:
            problems.append(f"라벨 불일치: {n} {k}")
        for e in r.get("evidence") or []:
            cid = e["chunk_id"]
            base = cid if cid in by_id else next((x for x in by_id if x.startswith(cid + "~")), None)
            if base is None:
                problems.append(f"없는 청크: {n} {k} {cid}")
                continue
            c = by_id[base]
            by_q.setdefault(n, []).append(EvidenceRef(
                doc_id=c.doc_id, chunk_id=cid, location=c.section or c.title, statement=k,
                grade=e.get("grade", "decisive"), note=r.get("note")))
    missing = [(q.number, k) for q in exam.items for k in q.statements() if (q.number, k) not in seen]
    problems += [f"라벨 없음: {n} {k}" for n, k in missing]
    for q in exam.items:
        q.evidence = by_q.get(q.number, [])
    exam_path.write_text(exam.model_dump_json(indent=2), encoding="utf-8")

    out = ROOT / a.csv
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["number", "statement", "label", "found", "decisive", "supporting", "note", "label_doubt",
                    "reviewer_ok", "reviewer_note"])
        for r in sorted(rows, key=lambda r: (int(r["number"]), str(r["statement"]))):
            ev = r.get("evidence") or []
            w.writerow([r["number"], r["statement"], "참" if r["label"] else "거짓", int(bool(r["found"])),
                        " ".join(e["chunk_id"] for e in ev if e.get("grade", "decisive") == "decisive"),
                        " ".join(e["chunk_id"] for e in ev if e.get("grade") == "supporting"),
                        r.get("note", ""), int(bool(r.get("label_doubt"))), "", ""])
    found = sum(bool(r["found"]) for r in rows)
    print(json.dumps({"statements": len(rows), "found": found, "not_found": len(rows) - found,
                      "label_doubt": [f"{r['number']}{r['statement']}" for r in rows if r.get("label_doubt")],
                      "evidence_refs": sum(len(v) for v in by_q.values()), "problems": problems,
                      "exam": str(exam_path.relative_to(ROOT)), "csv": str(out.relative_to(ROOT))},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

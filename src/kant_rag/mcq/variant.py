"""변형본 검증 도구 (`kant-rag diff-exam`): 원본 시험과 변형본(적대적 변형 등)을 진술 단위로 비교해
정답이 바뀌었을 수 있는 진술을 사람이 확인하도록 CSV 로 뽑는다.

표시 기준
- number_changed : 숫자(기간·금액·날짜·조문 번호)가 바뀜 → 참·거짓이 뒤집혔을 수 있음
- negation_changed : 부정 표현(않/아니/없/못/불가) 개수가 바뀜 → 극성이 뒤집혔을 수 있음
- double_negation : 변형본에 이중부정·우회 표현이 새로 생김 → 문장 해석이 모호할 수 있음
- large_edit : 문장 유사도 0.8 미만 → 내용 자체가 바뀌었을 수 있음
"""

from __future__ import annotations

import csv
import difflib
import json
import re
from pathlib import Path

from kant_rag.mcq.schemas import ExamQuestion, derive_statement_labels

NEG = re.compile(r"않|아니|없|못|불가|부정")
DOUBLE_NEG = re.compile(r"않는 것이 아니|않은 것은 아니|지 않을 수 없|없지 않|아니라고 할 수 없|아니지 않")


def load_items(path: Path) -> dict[int, ExamQuestion]:
    """시험 JSON(Exam/BarEvalSet) 또는 solve-text 실행 기록(records.jsonl, question 필드)."""
    if path.suffix == ".jsonl":
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("question"):
                q = ExamQuestion(**r["question"])
                out[q.number] = q
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    return {q["number"]: ExamQuestion(**q) for q in data["items"]}


def compare(orig: dict[int, ExamQuestion], var: dict[int, ExamQuestion]) -> list[dict]:
    rows = []
    for n in sorted(var):
        v, o = var[n], orig.get(n)
        if o is None:
            continue
        labels = derive_statement_labels(v) if v.answer else {}
        stem_changed = difflib.SequenceMatcher(None, o.stem, v.stem).ratio() < 0.98
        so, sv = o.statements(), v.statements()
        for k, text in sv.items():
            before = so.get(k, "")
            if text == before and not stem_changed:
                continue
            ratio = difflib.SequenceMatcher(None, before, text).ratio()
            flags = {
                "number_changed": re.findall(r"\d+", before) != re.findall(r"\d+", text),
                "negation_changed": len(NEG.findall(before)) != len(NEG.findall(text)),
                "double_negation": bool(DOUBLE_NEG.search(text)) and not DOUBLE_NEG.search(before),
                "large_edit": ratio < 0.8,
            }
            rows.append({
                "number": n, "key": k, "answer": v.answer, "label(정답 유지 가정)": labels.get(k),
                "check_needed": any(flags.values()), **flags, "stem_changed": stem_changed,
                "similarity": round(ratio, 3), "original": before, "variant": text,
                "human_ok(1=정답 유지,0=바뀜)": "", "note": "",
            })
    return rows


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["number"])
        w.writeheader()
        w.writerows(rows)

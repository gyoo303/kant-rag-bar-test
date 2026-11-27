"""붙여넣은 시험지 텍스트를 변환 단계 없이 바로 풀이 (`kant-rag solve-text`, Streamlit 선택형 탭).

- 문항 머리(`문  1.` / `【문 1】`)가 없으면 한 문항으로 간주
- 보기가 5개가 아닌 등 인식 못한 문항은 건너뛰고 알려 줌
- 결과: results/<시각>-<label>/records.jsonl · answers.csv (정답을 주면 채점)
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from kant_rag.config import Settings
from kant_rag.mcq.parse import Q_START, parse_exam_text
from kant_rag.mcq.schemas import ExamQuestion

CIRCLED = "①②③④⑤"


def parse_pasted(text: str, id_prefix: str = "TEXT") -> tuple[list[ExamQuestion], list[str]]:
    """텍스트 → (문항들, 문제 메시지). 문항 하나가 잘못돼도 나머지는 계속."""
    starts = list(Q_START.finditer(text))
    if not starts:
        text = "【문 1】\n" + text
        starts = list(Q_START.finditer(text))
    blocks = [text[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
              for i, m in enumerate(starts)]
    qs: list[ExamQuestion] = []
    problems: list[str] = []
    for b in blocks:
        try:
            qs += parse_exam_text(b, id_prefix=id_prefix)
        except ValueError as e:
            head = b.strip().splitlines()[0][:30] if b.strip() else "?"
            problems.append(f"{head}: 인식 실패 ({str(e).splitlines()[0][:120]})")
    return qs, problems


def parse_answers(spec: str | None) -> dict[int, int]:
    """'3,5,5' (1번부터 순서대로) 또는 number,answer CSV 경로."""
    if not spec:
        return {}
    p = Path(spec)
    if p.exists():
        with p.open(encoding="utf-8-sig") as f:
            return {int(r["number"]): int(str(r["answer"]).split("|")[0]) for r in csv.DictReader(f)}
    vals = [v.strip() for v in spec.replace(" ", ",").split(",") if v.strip()]
    return {i + 1: int(v) for i, v in enumerate(vals)}


def solve_text(settings: Settings, text: str, preset: str = "v3", mode: str = "hybrid_rerank",
               answers: str | None = None, label: str = "text", sets: list[str] | None = None) -> Path:
    from kant_rag.mcq.presets import PRESETS, apply_overrides, parse_sets
    from kant_rag.mcq.solver import MCQSolver
    from kant_rag.retrieval.pipeline import RetrievalMode

    qs, problems = parse_pasted(text)
    for msg in problems:
        print("⚠", msg)
    if not qs:
        raise SystemExit("문항을 인식하지 못했습니다. 문항은 '문 1.' 또는 '【문 1】', 보기는 ①~⑤ 로 시작해야 합니다.")
    key = parse_answers(answers)
    for q in qs:
        q.answer = key.get(q.number)
    print(f"{len(qs)}문항 인식: {[q.number for q in qs]} · preset={preset} · mode={mode}")

    overrides = {**PRESETS[preset], **parse_sets(sets or [])}
    s = apply_overrides(settings, overrides)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + label
    out = s.resolve(s.paths.results_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)
    solver = MCQSolver(s)
    rows = []
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for q in qs:
            r = solver.solve(q, RetrievalMode(mode), run_id)
            r["question"] = q.model_dump()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            pred = r.get("predicted")
            mark = "" if q.answer is None else (" ○" if pred == q.answer else f" × (정답 {CIRCLED[q.answer - 1]})")
            print(f"[문 {q.number}] 예측 {CIRCLED[pred - 1] if pred else '없음'}{mark}  "
                  f"status={r['status']}  {r['timing_ms'].get('total')}ms")
            for k, j in (r.get("judgments") or {}).items():
                src = " [지식]" if j.get("source") == "knowledge" else ""
                print(f"    {k}: {j['verdict']} ({j['confidence']:.2f}){src} {', '.join(j['cited_chunk_ids'][:3])}")
            rows.append([q.number, pred or "", q.answer or "", "" if q.answer is None else int(pred == q.answer),
                         r["status"]])
    with (out / "answers.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["number", "predicted", "answer", "correct", "status"])
        w.writerows(rows)
    (out / "summary.json").write_text(json.dumps({
        "run_id": run_id, "preset": preset, "mode": mode, "overrides": overrides,
        "questions": len(qs), "skipped": problems,
        "graded": sum(1 for r in rows if r[2] != ""), "correct": sum(1 for r in rows if r[3] == 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    graded = [r for r in rows if r[2] != ""]
    if graded:
        print(f"정답 {sum(r[3] for r in graded)}/{len(graded)}")
    print("saved:", out)
    return out

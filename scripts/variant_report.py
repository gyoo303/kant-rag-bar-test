"""변형본 성능 리포트 초안 생성 (서상혁 v2 변형본 리포트와 같은 구조): 요약 · 측정 기준 · 검색 · 사실 · 답변(4-①②③) · 결론 자리.

  uv run python scripts/variant_report.py results/<실행1> [results/<실행2> ...] --labels v6-b v6-a \
      --exam data/exam/bar11_gold30_v2.json --gold eval/2022-validation/gold30_v2var_refs.json \
      [--base docs/analysis/bar11-gold30-metrics.json --base-label v6] --out docs/analysis/bar11-gold30-v2var-v6-tables.md

표와 목록만 만든다. 해석(요약 문장·결론)은 사람이 덧붙인다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gold30_metrics import analyze, load_gold, load_records, summarize  # noqa: E402

CIRC = "①②③④⑤"
FORM_KO = {"single": "단일", "combination": "조합", "ox": "○×", "count": "개수", "blank": "괄호"}


def pct(a, b):
    return f"{a}/{b} ({a * 100 / b:.1f}%)" if b else "—"


def p(v):
    return f"{v * 100:.1f}%"


def load_exam(path: Path) -> dict:
    from kant_rag.mcq.io import load_bar_evalset
    return {q.number: q for q in load_bar_evalset(path).items}


def cause(qrow: dict, rec: dict) -> str:
    cls = qrow["classes"]
    sc = rec.get("option_scores") or {}
    top = max(sc.values()) if sc else None
    tied = [int(n) for n, v in sc.items() if top is not None and abs(v - top) < 1e-9]
    if "C" in cls or "D" in cls:
        return "오판" + (" + 유보" if "E" in cls else "")
    if "E" in cls and len(tied) > 1:
        return "유보 → 동점"
    if "E" in cls:
        return "유보"
    return "지문 판단은 맞음 → 보기 선택 (극성·형식·계산 확인)"


def build(runs, labels, exam, gold, base, base_label):
    A = [analyze(Path(r), gold) for r in runs]
    S = [summarize(a) for a in A]
    R = [load_records(Path(r)) for r in runs]
    cols = ([base_label] if base else []) + labels
    BS = [base["summary"]] if base else []
    allS = BS + S
    head = "| 지표 | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols)
    def line(name, f):
        return f"| {name} | " + " | ".join(f(s) for s in allS) + " |"
    wrong = [[x["number"] for x in a["q"] if not x["correct"]] for a in A]
    L = ["## 요약 (표)\n", head,
         line("문항 정답", lambda s: f"{s['q_correct']}/{s['questions']}"),
         "| 오답 문항 | " + ("— | " if base else "") + " | ".join(", ".join(map(str, w)) or "없음" for w in wrong) + " |",
         line("지문 정답 / 유보 / 오답", lambda s: f"{s['st_correct']} / {s['st_unknown']} / {s['st_wrong']}"),
         line("확신 오답 (≥0.9)", lambda s: str(s["confident_wrong"])),
         line("Recall@5 · Hit@5 · MRR", lambda s: f"{p(s['recall@5'])} · {p(s['hit@5'])} · {s['mrr']:.3f}"),
         line("Recall@1", lambda s: p(s["recall@1"])),
         line("Context Recall", lambda s: p(s["context_recall"])),
         line("인용 Recall · 인용 Precision", lambda s: f"{p(s['cited_recall'])} · {p(s['cited_precision'])}"),
         line("지문 A (정답 + 정답 근거 인용)", lambda s: pct(s["classes"].get("A", 0), s["statements"])),
         line("모든 지문이 A 인 문항", lambda s: f"{s['q_all_A']}/{s['questions']}"),
         line("인용 없이 단정한 판단", lambda s: str(s["uncited_judged"])),
         line("정답 근거가 입력에 없는데 맞힌 지문", lambda s: pct(s["outside_context_correct"], s["correct_n"])),
         line("문항당 시간 (평균·중앙)", lambda s: f"{s['time_mean']:.1f} · {s['time_median']:.1f}초"), ""]

    # 2. 검색
    L += ["## 2. 검색 — 의미 있는 문서가 검색되었나\n", head]
    for k in (1, 3, 5):
        L.append(line(f"Recall@{k}", lambda s, k=k: p(s[f"recall@{k}"])))
    for k in (1, 3, 5):
        L.append(line(f"Hit@{k}", lambda s, k=k: p(s[f"hit@{k}"])))
    for k in (1, 3, 5):
        L.append(line(f"Precision@{k}", lambda s, k=k: p(s[f"prec@{k}"])))
    L += [line("MRR", lambda s: f"{s['mrr']:.3f}"), ""]
    src = {(q["number"], s["statement"]): s.get("source", "") for q in gold.values() for s in q["statements"]}
    for lb, a in zip(labels, A):
        L += [f"### 지문 출처별 — {lb}\n", "| 지문 출처 | 지문 수 | Hit@5 | 분류 |\n|---|---|---|---|"]
        for name, test in (("원본 지문 그대로 (위치만 이동)", lambda s: s.startswith("원본") and "변경" not in s),
                           ("새로 쓰거나 문구를 바꾼 지문", lambda s: not (s.startswith("원본") and "변경" not in s))):
            rs = [r for r in a["rows"] if test(src.get((r["number"], r["statement"]), ""))]
            c = Counter(r["class"] for r in rs)
            L.append(f"| {name} | {len(rs)} | {pct(sum(r['hit@5'] for r in rs), len(rs))} | "
                     + " · ".join(f"{k} {c[k]}" for k in "ABCDE" if c[k]) + " |")
        miss = [r for r in a["rows"] if not r["hit@5"]]
        L += ["", f"**상위 5개에 정답 근거가 없던 지문 {len(miss)}개 — {lb}**\n",
              "| 문·지문 | 정답 근거 | 분류 | 판단 입력에 있음 |\n|---|---|---|---|"]
        for r in miss:
            L.append(f"| {r['number']} {r['statement']} | {', '.join(g[2:] for g in r['gold'])} | {r['class']} | "
                     f"{'예' if r['in_context'] else '아니오'} |")
        L.append("")

    # 3. 사실
    L += ["## 3. 사실 — 적합한 문서가 맥락으로 쓰였나\n", head,
          line("Context Recall", lambda s: p(s["context_recall"])),
          line("Context Precision", lambda s: p(s["context_precision"])),
          line("인용 Recall", lambda s: p(s["cited_recall"])),
          line("인용 Precision", lambda s: p(s["cited_precision"])),
          line("인용 원문 대조 (일치/불일치/없음)",
               lambda s: (lambda q: f"{q.get('True', 0)}/{q.get('False', 0)}/{q.get('None', 0)}")(s["quote"])
               if set(s["quote"]) - {"None"} else "—"), ""]
    for lb, a in zip(labels, A):
        inctx = [r for r in a["rows"] if r["in_context"] and not r["cited_gold"]]
        L += [f"**입력에 있는데 인용하지 않은 정답 근거 — {lb}** (지문 {len(inctx)}개)\n",
              "| 문·지문 | 분류 | 판단 (확신도) |\n|---|---|---|"]
        for r in inctx:
            L.append(f"| {r['number']} {r['statement']} | {r['class']} | {r['verdict']} ({r['confidence']}) |")
        L.append("")

    # 4. 답변
    L += ["## 4. 답변 — 최종 답을 맞혔나\n"]
    forms = sorted({q.form for q in exam.values()})
    subs = sorted({q.subject for q in exam.values() if q.subject})
    L += ["| 지표 | " + " | ".join(labels) + " |\n|---|" + "---|" * len(labels)]
    def lrow(name, f):
        return f"| {name} | " + " | ".join(f(a, s, r) for a, s, r in zip(A, S, R)) + " |"
    L += [lrow("문항 정답", lambda a, s, r: pct(s["q_correct"], s["questions"])),
          lrow("형식별", lambda a, s, r: " · ".join(
              f"{FORM_KO.get(f, f)} {sum(x['correct'] for x in a['q'] if exam[x['number']].form == f)}/"
              f"{sum(exam[x['number']].form == f for x in a['q'])}" for f in forms)),
          lrow("과목별", lambda a, s, r: " · ".join(
              f"{sb} {sum(x['correct'] for x in a['q'] if exam[x['number']].subject == sb)}/"
              f"{sum(exam[x['number']].subject == sb for x in a['q'])}" for sb in subs)),
          lrow("지문 정답", lambda a, s, r: pct(s["st_correct"], s["statements"])),
          lrow("지문 유보 / 오답", lambda a, s, r: f"{s['st_unknown']} / {s['st_wrong']}"),
          lrow("확신 오답 (≥0.9)", lambda a, s, r: ", ".join(
              f"{x['number']} {x['statement']} {x['confidence']}" for x in a["rows"]
              if not x["correct"] and x["verdict"] != "unknown" and (x["confidence"] or 0) >= 0.9) or "0"),
          lrow("상태", lambda a, s, r: " · ".join(f"{k} {v}" for k, v in Counter(x["status"] for x in a["q"]).most_common())), ""]
    for lb, a, rr in zip(labels, A, R):
        bad = [x for x in a["q"] if not x["correct"]]
        L += [f"**오답 {len(bad)}문항의 원인 — {lb}**\n", "| 문 | 지문 분류 | 원인 (자동 분류) | 예측 / 정답 | 보기 점수 상위 |\n|---|---|---|---|---|"]
        for x in bad:
            rec = rr[x["number"]]
            sc = sorted((rec.get("option_scores") or {}).items(), key=lambda kv: -kv[1])[:3]
            L.append(f"| {x['number']} | {''.join(x['classes'])} | {cause(x, rec)} | "
                     f"{CIRC[x['predicted'] - 1] if x['predicted'] else '—'} / {CIRC[x['answer'] - 1]} | "
                     + " · ".join(f"{CIRC[int(n) - 1]} {v:.3g}" for n, v in sc) + " |")
        L.append("")
    L += ["### 4-① 5개 지문을 정확한 근거로 판단했는가\n", head]
    for c in "ABCDE":
        L.append(line(c, lambda s, c=c: pct(s["classes"].get(c, 0), s["statements"])))
    L += [line("모든 지문이 A 인 문항", lambda s: f"{s['q_all_A']}/{s['questions']}"),
          line("정답 문항 중 B 가 섞인 문항", lambda s: str(s["q_correct_with_B"])),
          line("근거 의존도 A/(A+B)", lambda s: p(s["classes"].get("A", 0) / max(1, s["classes"].get("A", 0) + s["classes"].get("B", 0)))), ""]
    for lb, a in zip(labels, A):
        allA = [x["number"] for x in a["q"] if all(c == "A" for c in x["classes"])]
        L.append(f"- {lb} 모든 지문 A: {', '.join(map(str, allA))}"
                 + (f" (그중 오답: {', '.join(str(n) for n in allA if n in [y['number'] for y in a['q'] if not y['correct']])})"
                    if any(n in [y['number'] for y in a['q'] if not y['correct']] for n in allA) else ""))
    L += ["", "### 4-② 추가 추론(생성형 모델 판단 개입)이 발생했는가\n", head,
          line("인용 없이 단정한 판단", lambda s: str(s["uncited_judged"])),
          line("정답 근거가 입력에 없는데 맞힌 지문", lambda s: pct(s["outside_context_correct"], s["correct_n"])),
          line("2차 검색으로 판단이 바뀐 지문", lambda s: str(s.get("researched", 0))),
          line("함정 판례가 입력에 / 인용", lambda s: f"{s.get('trap_in_context', 0)} / {s.get('trap_cited', 0)}"), ""]
    for lb, a in zip(labels, A):
        L.append(f"- {lb} 근거 밖 정답: " + ", ".join(f"{r['number']} {r['statement']}" for r in a["rows"]
                                                    if r["correct"] and not r["in_context"]))
        L.append(f"- {lb} D(근거 없이 틀림): " + (", ".join(f"{r['number']} {r['statement']} ({r['verdict']} {r['confidence']})"
                                                       for r in a["rows"] if r["class"] == "D") or "없음"))
    L += ["", "### 4-③ 공략 축별\n", "| 축 | " + " | ".join(f"{lb} 문항 정답 · 지문 분류" for lb in labels) + " |\n|---|"
          + "---|" * len(labels)]
    axes = sorted({ax for q in gold.values() for ax in q.get("axes", [])})
    for ax in axes:
        cells = []
        for a in A:
            qs = [x for x in a["q"] if ax in x["axes"]]
            cnt = Counter(c for x in qs for c in x["classes"])
            cells.append(f"{sum(x['correct'] for x in qs)}/{len(qs)} · " + " ".join(f"{k}{cnt[k]}" for k in "ABCDE" if cnt[k]))
        L.append(f"| {ax} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("--exam", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--base", default=None, help="비교 기준 지표 JSON (gold30_metrics 출력)")
    ap.add_argument("--base-label", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    labels = a.labels or [Path(r).name for r in a.runs]
    base = None
    if a.base:
        d = json.loads(Path(a.base).read_text(encoding="utf-8"))
        base = d[a.base_label] if a.base_label else next(iter(d.values()))
    md = build(a.runs, labels, load_exam(Path(a.exam)), load_gold(a.gold), base, a.base_label or "기준")
    out = ROOT / a.out
    out.write_text(md, encoding="utf-8")
    print(md.split("## 2.")[0])
    print("saved:", out)


if __name__ == "__main__":
    main()

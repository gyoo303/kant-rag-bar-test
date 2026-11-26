"""2022 검증 세트(근거 확정 30문항) 지표: 검색·사실·답변 + 지문 A~E 분류 + 추가 추론 개입.

  uv run python scripts/gold30_metrics.py results/<v2 실행> [results/<v6 실행> ...] --labels v2 v6 \
      [--closed results/<closed-book 실행>] --out docs/analysis/bar11-gold30-metrics.md

정답 근거: eval/2022-validation/gold30_refs.json (지문별 판례 사건번호·'법령명 제N조').
에이전트 청크 id 는 근거 단위로 맞춘다: 판례 CASE#<사건번호>#<항목>(~조각) → 첫 사건번호,
조문 <doc_id>#제N조(-항 조각·~조각) → '법령명|제N조' (doc_id → 법령명은 data/documents.csv).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_NO = re.compile(r"\d{2,4}[가-힣]{1,4}\d+")
KS = (1, 3, 5)


def _titles() -> dict[str, str]:
    with (ROOT / "data" / "documents.csv").open(encoding="utf-8") as f:
        return {r["doc_id"]: r["title"] for r in csv.DictReader(f)}


TITLES = _titles()


def ref_key(ref: str) -> str:
    """정답 근거 표기 → 비교 키. '2005다71659, 71666' → 'C:2005다71659', '상법 제542조의12-1' → 'S:상법|제542조의12'."""
    m = re.match(r"(.+?)\s*(제\d+조(?:의\d+)?)", ref)
    if m and not CASE_NO.match(ref):
        return f"S:{re.sub(r'\s', '', m.group(1))}|{m.group(2)}"
    c = CASE_NO.search(ref)
    return f"C:{c.group(0)}" if c else f"?:{ref}"


def chunk_key(cid: str) -> str:
    if cid.startswith("CASE#"):
        body = cid[5:].rsplit("#", 1)[0]
        c = CASE_NO.search(body)
        return f"C:{c.group(0)}" if c else f"?:{cid}"
    doc, _, art = cid.partition("#")
    art = re.split(r"[~]", art)[0]
    art = re.sub(r"-\d+$", "", art)
    m = re.match(r"제\d+조(?:의\d+)?", art)
    title = re.sub(r"\s", "", TITLES.get(doc, doc))
    return f"S:{title}|{m.group(0)}" if m else f"?:{cid}"


GOLD = ROOT / "eval" / "2022-validation" / "gold30_refs.json"


def load_gold(path: Path | None = None) -> dict[int, dict]:
    g = json.loads(Path(path or GOLD).read_text(encoding="utf-8"))
    return {q["number"]: q for q in g}


def load_records(run: Path) -> dict[int, dict]:
    out = {}
    for line in (run / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("eval", {}).get("kind", "mcq") == "mcq":
                out[r["number"]] = r
    return out


def _pct(a, b):
    return f"{a}/{b} ({a * 100 / b:.1f}%)" if b else "—"


def analyze(run: Path, gold: dict[int, dict], closed: dict[int, dict] | None = None) -> dict:
    recs = load_records(run)
    rows = []  # 지문 단위
    qrows = []
    for n, gq in sorted(gold.items()):
        r = recs.get(n)
        if r is None:
            continue
        ctx = [chunk_key(x) for x in (r.get("context_chunk_ids") or [])]
        ctx_set = set(ctx)
        q_gold = {ref_key(x["ref"]) for s in gq["statements"] for x in s["refs"]}
        js = r.get("judgments") or {}
        qcls = []
        for s in gq["statements"]:
            k = s["statement"]
            G = {ref_key(x["ref"]) for x in s["refs"]}
            ret = [chunk_key(x["chunk_id"]) for x in (r.get("retrieval") or {}).get(k, [])]
            j = js.get(k) or {}
            verdict = j.get("verdict", "unknown")
            want = "true" if s["label"] else "false"
            cited = [chunk_key(x) for x in (j.get("cited_chunk_ids") or [])]
            in_ctx = bool(G & ctx_set)
            cited_gold = bool(G & set(cited))
            correct = verdict == want
            traps = {ref_key(x["ref"]) for x in s.get("traps", []) if ref_key(x["ref"]).startswith("C:")}
            if verdict == "unknown":
                cls = "E"
            elif correct:
                cls = "A" if cited_gold else "B"
            else:
                cls = "C" if in_ctx else "D"
            first = next((i + 1 for i, x in enumerate(ret) if x in G), None)
            row = {"number": n, "statement": k, "label": s["label"], "verdict": verdict,
                   "confidence": j.get("confidence"), "correct": correct, "class": cls,
                   "gold": sorted(G), "first_rank": first, "in_context": in_ctx, "cited_gold": cited_gold,
                   "cited": len(cited), "cited_gold_n": sum(c in G for c in cited),
                   "quote_check": (r.get("quote_check") or {}).get(k),
                   "researched": k in ((r.get("research") or {}).get("changed") or {}),
                   "trap": sorted(traps), "trap_in_context": bool(traps & ctx_set), "trap_cited": bool(traps & set(cited))}
            for kk in KS:
                top = ret[:kk]
                row[f"recall@{kk}"] = len(G & set(top)) / len(G) if G else 0
                row[f"hit@{kk}"] = bool(G & set(top))
                row[f"prec@{kk}"] = sum(x in G for x in top) / kk
            if closed and n in closed:
                cj = (closed[n].get("judgments") or {}).get(k) or {}
                row["closed_correct"] = cj.get("verdict") == want
            rows.append(row)
            qcls.append(cls)
        qrows.append({"number": n, "form": gq.get("form"), "axes": gq.get("axes", []), "predicted": r.get("predicted"), "answer": gq["answer"],
                      "correct": r.get("predicted") == gq["answer"], "classes": qcls,
                      "ctx_n": len(ctx), "ctx_gold_n": sum(x in q_gold for x in ctx),
                      "time_s": (r.get("timing_ms") or {}).get("total", 0) / 1000,
                      "status": r.get("status")})
    return {"run": run.name, "rows": rows, "q": qrows}


def summarize(a: dict) -> dict:
    rows, q = a["rows"], a["q"]
    n = len(rows)
    mean = lambda key: sum(r[key] for r in rows) / n if n else 0  # noqa: E731
    rr = [1 / r["first_rank"] for r in rows if r["first_rank"]]
    cls = Counter(r["class"] for r in rows)
    correct = [r for r in rows if r["correct"]]
    s = {
        "questions": len(q), "q_correct": sum(x["correct"] for x in q),
        "statements": n,
        **{f"recall@{k}": mean(f"recall@{k}") for k in KS},
        **{f"hit@{k}": mean(f"hit@{k}") for k in KS},
        **{f"prec@{k}": mean(f"prec@{k}") for k in KS},
        "mrr": sum(rr) / n if n else 0,
        "context_recall": mean("in_context"),
        "context_precision": (sum(x["ctx_gold_n"] for x in q) / sum(x["ctx_n"] for x in q)) if q else 0,
        "cited_recall": mean("cited_gold"),
        "cited_precision": (sum(r["cited_gold_n"] for r in rows) / sum(r["cited"] for r in rows))
        if sum(r["cited"] for r in rows) else 0,
        "st_correct": len(correct), "st_unknown": cls["E"], "st_wrong": cls["C"] + cls["D"],
        "confident_wrong": sum(1 for r in rows if not r["correct"] and r["verdict"] != "unknown"
                               and (r["confidence"] or 0) >= 0.9),
        "classes": dict(cls),
        "q_all_A": sum(all(c == "A" for c in x["classes"]) for x in q),
        "q_correct_with_B": sum(x["correct"] and "B" in x["classes"] for x in q),
        "outside_context_correct": sum(1 for r in correct if not r["in_context"]),
        "correct_n": len(correct),
        "uncited_judged": sum(1 for r in rows if r["verdict"] != "unknown" and r["cited"] == 0),
        "uncited_judged_correct": sum(1 for r in rows if r["verdict"] != "unknown" and r["cited"] == 0 and r["correct"]),
        "quote": Counter(str(r["quote_check"]) for r in rows if r["verdict"] != "unknown"),
        "researched": sum(r["researched"] for r in rows),
        "trap_statements": sum(bool(r["trap"]) for r in rows),
        "trap_in_context": sum(r["trap_in_context"] for r in rows),
        "trap_cited": sum(r["trap_cited"] for r in rows),
        "axes": {ax: [sum(x["correct"] for x in q if ax in x["axes"]), sum(ax in x["axes"] for x in q)]
                 for ax in sorted({a for x in q for a in x["axes"]})},
        "time_mean": statistics.mean(x["time_s"] for x in q) if q else 0,
        "time_median": statistics.median(x["time_s"] for x in q) if q else 0,
    }
    if any("closed_correct" in r for r in rows):
        s["cross"] = Counter((r["correct"], r.get("closed_correct")) for r in rows if "closed_correct" in r)
    return s


def render(analyses: list[dict], labels: list[str]) -> str:
    S = [summarize(a) for a in analyses]
    L = ["# 2022 검증 세트(근거 확정 30문항) 지표\n",
         f"> 실행: {', '.join(f'{lb} = `{a['run']}`' for lb, a in zip(labels, analyses))} · 정답 근거 `eval/2022-validation/gold30_refs.json` "
         "(지문 139 · 근거 142) · 판례는 사건번호, 조문은 '법령명 제N조' 단위로 맞춤\n"]
    head = "| 지표 | " + " | ".join(labels) + " |\n|---|" + "---|" * len(labels)
    def line(name, f):
        return f"| {name} | " + " | ".join(f(s) for s in S) + " |"
    p = lambda v: f"{v * 100:.1f}%"  # noqa: E731
    L += ["## 1. 요약\n", head,
          line("**문항 정답**", lambda s: f"**{s['q_correct']}/{s['questions']}**"),
          line("완전 근거 정답 (모든 지문 A)", lambda s: _pct(s["q_all_A"], s["questions"])),
          line("검색 Recall@5", lambda s: p(s["recall@5"])),
          line("Context Recall", lambda s: p(s["context_recall"])),
          line("인용 Recall (정답 근거 인용)", lambda s: p(s["cited_recall"])),
          line("지문 정답 / 유보 / 오답", lambda s: f"{s['st_correct']} / {s['st_unknown']} / {s['st_wrong']}"),
          line("문항당 시간 (평균·중앙)", lambda s: f"{s['time_mean']:.1f}·{s['time_median']:.1f}초"), ""]
    L += ["## 2. 검색 — 의미 있는 문서가 검색되었나\n",
          "지문마다 검색 결과 상위 k (진술별 retrieval 목록)와 정답 근거를 비교.\n", head]
    for k in KS:
        L.append(line(f"Recall@{k}", lambda s, k=k: p(s[f"recall@{k}"])))
    for k in KS:
        L.append(line(f"Hit@{k}", lambda s, k=k: p(s[f"hit@{k}"])))
    for k in KS:
        L.append(line(f"Precision@{k}", lambda s, k=k: p(s[f"prec@{k}"])))
    L += [line("MRR", lambda s: f"{s['mrr']:.3f}"), ""]
    L += ["## 3. 사실 — 적합한 문서가 맥락으로 쓰였나\n", head,
          line("Context Recall (정답 근거가 판단 입력에 들어감)", lambda s: p(s["context_recall"])),
          line("Context Precision (판단 입력 중 정답 근거 비율)", lambda s: p(s["context_precision"])),
          line("인용 Recall (판단이 정답 근거를 인용)", lambda s: p(s["cited_recall"])),
          line("인용 Precision (인용한 청크 중 정답 근거)", lambda s: p(s["cited_precision"])),
          line("인용 원문 대조 (일치/불일치/인용 없음)",
               lambda s: f"{s['quote'].get('True', 0)}/{s['quote'].get('False', 0)}/{s['quote'].get('None', 0)}"
               if set(s["quote"]) - {"None"} else "— (대조 안 함)"), ""]
    L += ["## 4. 답변 — 최종 답을 맞혔나\n", head,
          line("문항 정답", lambda s: _pct(s["q_correct"], s["questions"])),
          line("지문 정답", lambda s: _pct(s["st_correct"], s["statements"])),
          line("지문 유보", lambda s: str(s["st_unknown"])),
          line("지문 오답 (확신 오답 ≥0.9)", lambda s: f"{s['st_wrong']} ({s['confident_wrong']})"), ""]
    L += ["### 4-① 5개 지문을 정확한 근거로 판단했는가 (지문 A~E)\n",
          "A 근거 기반 정답(정답 + 정답 근거 인용) · B 정답이지만 정답 근거 미인용 · C 정답 근거가 입력에 있었는데 틀림 · "
          "D 정답 근거가 입력에 없고 틀림 · E 유보\n", head]
    for c in "ABCDE":
        L.append(line(c, lambda s, c=c: _pct(s["classes"].get(c, 0), s["statements"])))
    L += [line("**완전 근거 정답 문항 (모든 지문 A)**", lambda s: _pct(s["q_all_A"], s["questions"])),
          line("정답 문항 중 B 가 섞인 문항", lambda s: str(s["q_correct_with_B"])),
          line("근거 의존도 A/(A+B)", lambda s: p(s["classes"].get("A", 0) / max(1, s["classes"].get("A", 0) + s["classes"].get("B", 0)))), ""]
    L += ["### 4-② 추가 추론(생성형 모델 판단 개입)이 발생했는가\n", head,
          line("근거 밖 정답 (정답 근거가 입력에 없는데 맞힘)", lambda s: _pct(s["outside_context_correct"], s["correct_n"])),
          line("인용 없이 단정한 판단 (그중 정답)", lambda s: f"{s['uncited_judged']} ({s['uncited_judged_correct']})"),
          line("2차 검색으로 바뀐 지문", lambda s: str(s["researched"]))]
    if any("cross" in s for s in S):
        L += [line("RAG만 맞음 / closed-book만 맞음 / 둘 다 / 둘 다 틀림",
                   lambda s: (lambda c: f"{c.get((True, False), 0)} / {c.get((False, True), 0)} / {c.get((True, True), 0)} / {c.get((False, False), 0)}")(s["cross"]) if "cross" in s else "—")]
    else:
        L.append("\n(closed-book 실행을 `--closed` 로 주면 RAG × closed-book 교차표가 추가됩니다.)")
    if any(s["trap_statements"] for s in S):
        L += ["", "### 함정 판례 (변형본 답안의 '함정' 판례: 기준일 뒤 변경·옛 법리 미끼)\n", head,
              line("함정이 걸린 지문", lambda s: str(s["trap_statements"])),
              line("함정 판례가 판단 입력에 들어감", lambda s: str(s["trap_in_context"])),
              line("함정 판례를 인용", lambda s: str(s["trap_cited"]))]
    if any(s["axes"] for s in S):
        axes = sorted({a for s in S for a in s["axes"]})
        L += ["", "### 공략 축별 문항 정답\n", head]
        for ax in axes:
            L.append(line(ax, lambda s, ax=ax: "{}/{}".format(*s["axes"].get(ax, [0, 0]))))
    L.append("")
    for lb, a in zip(labels, analyses):
        L += [f"## 5. 문항별 — {lb}\n", "| 문 | 예측 | 정답 | 결과 | 지문 분류 | 판단 입력 중 정답 근거 | 시간(초) |\n|---|---|---|---|---|---|---|"]
        for x in a["q"]:
            L.append(f"| {x['number']} | {x['predicted']} | {x['answer']} | {'✅' if x['correct'] else '❌'} | {''.join(x['classes'])} | "
                     f"{x['ctx_gold_n']}/{x['ctx_n']} | {x['time_s']:.1f} |")
        L += ["", f"### A 가 아닌 지문 — {lb}\n",
              "| 문 | 지문 | 정답 | 판단 (확신도) | 분류 | 정답 근거 | 검색 첫 순위 | 입력에 있음 |\n|---|---|---|---|---|---|---|---|"]
        for r in a["rows"]:
            if r["class"] == "A":
                continue
            L.append(f"| {r['number']} | {r['statement']} | {'참' if r['label'] else '거짓'} | {r['verdict']} ({r['confidence']}) | "
                     f"{r['class']} | {', '.join(g[2:] for g in r['gold'])} | {r['first_rank'] or '—'} | {'예' if r['in_context'] else '아니오'} |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("--closed", default=None)
    ap.add_argument("--out", default="docs/analysis/bar11-gold30-metrics.md")
    ap.add_argument("--gold", default=None, help="정답 근거 JSON (기본 eval/2022-validation/gold30_refs.json)")
    a = ap.parse_args()
    gold = load_gold(a.gold)
    closed = load_records(Path(a.closed)) if a.closed else None
    analyses = [analyze(Path(r), gold, closed) for r in a.runs]
    labels = a.labels or [Path(r).name for r in a.runs]
    md = render(analyses, labels)
    out = ROOT / a.out
    out.write_text(md, encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(
        {lb: {"summary": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in summarize(x).items() if k != "cross"},
              "rows": x["rows"], "questions": x["q"]} for lb, x in zip(labels, analyses)},
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md.split("## 2.")[0])
    print("saved:", out)


if __name__ == "__main__":
    main()

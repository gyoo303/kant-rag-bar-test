"""시험 풀이 분석 (서상혁 브랜치 report-retrieval-reasoning.md 와 같은 기준):
(1) 검색 품질 — 판단에 인용된 근거의 벡터·BM25·재정렬 순위, (2) 검색 결과를 쓴 추론·검색이 부족할 때의 추론,
(3) 정답에 결정적으로 기여한 요소.

실행마다 run_dir 안에 필요한 것:
  runs.jsonl                  풀이 기록
  retrieval_replay.json       scripts/replay_retrieval.py — 같은 검색어의 단계별 순위
  evidence_judgments.json     (선택) scripts/judge_evidence.py — 지문별 결정 근거 문서 독립 판정
사용:
  uv run python scripts/analyze_run.py <약칭>=<run_dir>=<exam json>[=<정답 csv>] ...
→ 표준출력에 표(markdown), 각 run_dir/analysis.json
정답은 시험 JSON 의 answer, 정답 csv(number,answer)를 주면 그것을 쓴다.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

from civil_rag.exam.solver import (
    choice_expectation,
    choose_answer,
    is_count_question,
    split_statements,
    stem_polarity,
)
from civil_rag.ingest.build import load_chunks
from civil_rag.ingest.chunking import parse_ref_articles

STMT_LISTS = ("", ":alone", ":issue", ":exception", ":plain", ":retry")


def doc_key(cid: str, chunks: dict) -> str:
    ch = chunks.get(cid)
    return ch.doc_id if ch is not None and ch.doc_type == "prec" else cid


def drank(ids: list[str], target: str, chunks: dict) -> int | None:
    seen: list[str] = []
    for cid in ids:
        dk = doc_key(cid, chunks)
        if dk not in seen:
            seen.append(dk)
        if dk == target:
            return len(seen)
    return None


def truth_map(item: dict, answer: int) -> dict[str, str | None]:
    st = split_statements(item.get("passage"))
    pol = stem_polarity(item["stem"])
    if st:
        if is_count_question(item["stem"]):
            return {k: None for k in st}
        exp = choice_expectation(item["choices"][str(answer)], list(st), pol)
        return {k: (exp or {}).get(k) for k in st}
    t = "X" if pol == "incorrect" else "O"
    return {str(n): (t if int(n) == answer else ("O" if t == "X" else "X")) for n in item["choices"]}


def analyze(name: str, run_dir: str, exam_file: str, answers_csv: str | None, chunks: dict) -> dict:
    run = Path(run_dir)
    runs = {json.loads(line)["no"]: json.loads(line) for line in (run / "runs.jsonl").open(encoding="utf-8")}
    items = {i["no"]: i for i in json.loads(Path(exam_file).read_text(encoding="utf-8"))["items"]}
    if answers_csv:
        key = {int(r["number"]): int(r["answer"]) for r in csv.DictReader(open(answers_csv, encoding="utf-8-sig"))}
    else:
        key = {n: int(i["answer"]) for n, i in items.items() if i.get("answer")}
    rp_path = run / "retrieval_replay.json"
    replay = json.loads(rp_path.read_text(encoding="utf-8"))["items"] if rp_path.exists() else {}
    jp = run / "evidence_judgments.json"
    judged = {j["no"]: j for j in json.loads(jp.read_text(encoding="utf-8"))} if jp.exists() else {}

    stmts, cited_docs, questions = [], [], []
    for no in sorted(runs):
        rec, it = runs[no], items[no]
        truth = truth_map(it, key[no])
        verdicts = rec.get("choice_verdicts") or {}
        plan = (rec.get("queries") or {}).get("plan", {})
        rp = replay.get(str(no), {})
        whole = rp.get("whole", {})
        q_classes = []
        for k, v in verdicts.items():
            t = truth.get(k)
            cited = [doc_key(c, chunks) for c in (v.get("cited") or [])]
            cited = list(dict.fromkeys(cited))
            grounded = bool(v.get("grounded"))
            ev = bool(cited) and grounded
            ok = (v.get("verdict") == t) if t else None
            cls = None if ok is None else (("E+" if ok else "E-") if ev else ("K+" if ok else "K-"))
            first = v.get("first") or {}
            flipped = bool(first) and first.get("verdict") != v.get("verdict")
            p = plan.get(k, {}) if isinstance(plan.get(k), dict) else {}
            named_keys = {x for a in (p.get("articles") or []) for x in parse_ref_articles(a)}
            j = (judged.get(no) or {}).get("statements", {}).get(k)
            stmts.append({"run": name, "no": no, "key": k, "class": cls, "votes": v.get("votes"), "flipped": flipped,
                          "flip_fixed": flipped and ok is True, "retried": bool(v.get("retried")),
                          "coverage": (j or {}).get("coverage")})
            q_classes.append(cls)
            if not ev or not rp:
                continue
            lists = [rp[k + s] for s in STMT_LISTS if (k + s) in rp]
            for D in cited:
                vr = [drank(L["vector"], D, chunks) for L in lists]
                br = [drank(L["bm25"], D, chunks) for L in lists]
                fr = [drank(L["fused"], D, chunks) for L in lists if L["mode"] == "C"]
                rr = [drank(L["reranked"], D, chunks) for L in lists if L["mode"] == "C"]
                fin = [drank(L["reranked"] or L["fused"], D, chunks) for L in lists]
                best = lambda xs: min([x for x in xs if x], default=None)  # noqa: E731
                origin = "search"
                if best(fin) is None:
                    if D in named_keys:
                        origin = "named"
                    elif whole and drank(whole.get("reranked") or whole.get("fused", []), D, chunks):
                        origin = "whole"
                    elif D.startswith("law:"):
                        origin = "junyong/law-quota"
                    else:
                        origin = "other"
                uplift = any(f and f >= 6 and r and r <= 5 for f, r in zip(fr, rr))
                cited_docs.append({"run": name, "no": no, "key": k, "doc": D, "ok": ok, "vector": best(vr),
                                   "bm25": best(br), "final": best(fin), "origin": origin, "uplift": uplift,
                                   "has_rerank": any(L["mode"] == "C" for L in lists)})
        pred_ok = rec.get("predicted") == key[no]
        questions.append({"run": name, "no": no, "correct": pred_ok, "classes": q_classes,
                          "flip_fixed": any(s["flip_fixed"] for s in stmts if s["run"] == name and s["no"] == no)})
    out = {"name": name, "score": sum(q["correct"] for q in questions), "n": len(questions),
           "statements": stmts, "cited": cited_docs, "questions": questions}
    (run / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def bucket_row(c: list[dict]) -> list[str]:
    n = len(c) or 1
    v = [x["vector"] for x in c]
    b = lambda lo, hi: sum(1 for x in v if x and lo <= x <= hi)  # noqa: E731
    out20 = sum(1 for x in v if not x)
    return [str(b(1, 1)), str(b(2, 5)), str(b(6, 10)), str(b(11, 20)), f"**{out20} ({out20 / n:.0%})**",
            f"{b(1, 5) / n:.0%}"]


def report(results: list[dict]) -> str:
    L = []
    L.append("### 진술 단위 — 판단에 쓰인 근거는 어디서 왔나\n")
    L.append("| 실행 | 정답 | 진술(정답 O/X 확정) | E+ | E− | K+ / K− |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        cs = Counter(s["class"] for s in r["statements"] if s["class"])
        n = sum(cs.values())
        L.append(f"| {r['name']} | {r['score']}/{r['n']} | {n} | {cs['E+']} ({cs['E+'] / n:.0%}) | {cs['E-']} | "
                 f"{cs['K+']} / {cs['K-']} |")
    L.append("\n### 벡터 검색 단독 품질 — 판단에 인용된 근거의 벡터 순위 (문서 단위, 그 진술의 검색어 중 최고)\n")
    L.append("| 실행 | 인용 근거 | 벡터 1위 | 2~5위 | 6~10위 | 11~20위 | 벡터 상위 20 밖 | 벡터 상위 5 안 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        c = r["cited"]
        L.append(f"| {r['name']} | {len(c)} | " + " | ".join(bucket_row(c)) + " |")
    L.append("\n| 실행 | BM25 상위 5 안 | BM25 상위 20 밖 | 재정렬이 결합 6위 이하 → 최종 5위 안 | 최종 1위 | 검색 밖 경로 |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        c = r["cited"]
        n = len(c) or 1
        b5 = sum(1 for x in c if x["bm25"] and x["bm25"] <= 5)
        bout = sum(1 for x in c if not x["bm25"])
        up = sum(1 for x in c if x["uplift"])
        f1 = sum(1 for x in c if x["final"] == 1)
        org = Counter(x["origin"] for x in c if x["origin"] != "search")
        rr = any(x.get("has_rerank") for x in c)
        upc = f"{up} ({up / n:.0%})" if rr else "— (재정렬 재현 안 함)"
        f1c = f"{f1} ({f1 / n:.0%})" if rr else f"결합 1위 {f1} ({f1 / n:.0%})"
        L.append(f"| {r['name']} | {b5 / n:.0%} | {bout} ({bout / n:.0%}) | {upc} | {f1c} | "
                 + (", ".join(f"{k} {v}" for k, v in org.items()) or "—") + " |")
    L.append("\n### 문항별 해결 경로 (정답 문항)\n")
    L.append("| 실행 | 정답 | 모든 진술을 검색 근거로 | 번호 계산 흡수 | 지식 판단 포함 | 재검토로 바로잡음 |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        qs = [q for q in r["questions"] if q["correct"]]
        known = lambda q: [c for c in q["classes"] if c]  # noqa: E731
        allE = sum(1 for q in qs if known(q) and all(c == "E+" for c in known(q)))
        absorb = sum(1 for q in qs if any(c in ("E-", "K-") for c in known(q)))
        know = sum(1 for q in qs if any(c == "K+" for c in known(q)))
        fix = sum(1 for q in qs if q["flip_fixed"])
        L.append(f"| {r['name']} | {len(qs)} | {allE} | {absorb} | {know} | {fix} |")
    return "\n".join(L)


def main(args: list[str]) -> None:
    chunks = {c.chunk_id: c for c in load_chunks()}
    results = []
    for a in args:
        parts = a.split("=")
        name, run_dir, exam = parts[0], parts[1], parts[2]
        results.append(analyze(name, run_dir, exam, parts[3] if len(parts) > 3 else None, chunks))
    print(report(results))


if __name__ == "__main__":
    main(sys.argv[1:])

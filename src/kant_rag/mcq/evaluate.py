"""선택형 평가 실행: results/<run_id>/mcq_records.jsonl, grading.csv, summary.json.

자동 지표: 정답률(예측 번호 == 확정 정답), Hit@5(허용 근거가 어느 진술의 top-5 에든 있으면 1),
진술 판단 정확도(statement_labels 가 있을 때), 호출 성공/지연.
사람 채점: 근거 적합(인용이 판단을 뒷받침하는가), 근거 없음 문항의 정보 부족 안내.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
import uuid
from pathlib import Path

from kant_rag.agent import KnowledgeAgent
from kant_rag.config import Settings
from kant_rag.mcq.io import check_bar_composition, load_bar_evalset
from kant_rag.mcq.schemas import ExamQuestion
from kant_rag.mcq.solver import MCQSolver
from kant_rag.retrieval.pipeline import RetrievalMode

ERRORS = ("retrieval_error", "generation_error")


def mcq_hit_at_k(rec: dict, q: ExamQuestion, k: int = 5) -> int | None:
    if not q.evidence:
        return None  # 근거 미표기 문항은 Hit@5 분모에서 제외 (보고서에 명시)
    allowed = {e.chunk_id for e in q.evidence}
    return int(any(matches(r["chunk_id"], allowed) for rs in (rec.get("retrieval") or {}).values() for r in rs[:k]))


def matches(chunk_id: str, allowed: set[str]) -> bool:
    """허용 근거가 분할 전 ID(예: CASE#…#2)이면 분할 조각(CASE#…#2~1)도 인정."""
    return chunk_id in allowed or chunk_id.split("~")[0] in allowed


def statement_accuracy(rec: dict, q: ExamQuestion) -> tuple[int, int]:
    if not q.statement_labels or not rec.get("judgments"):
        return 0, 0
    ok = n = 0
    for key, label in q.statement_labels.items():
        j = rec["judgments"].get(key)
        n += 1
        ok += int(j is not None and j["verdict"] == ("true" if label else "false"))
    return ok, n


def _latency(recs: list[dict], status_of) -> dict:
    ok = [r["timing_ms"]["total"] for r in recs if status_of(r) not in ERRORS]
    return {"n_success": len(ok), "n_total": len(recs), "n_error": len(recs) - len(ok),
            "mean_ms": round(statistics.mean(ok), 1) if ok else None,
            "median_ms": round(statistics.median(ok), 1) if ok else None}


def _statement_breakdown(recs: list[dict], items: list[ExamQuestion]) -> dict:
    """진술 단위: 정답 / 유보 / 확신 오답, 그리고 지식으로 채운 진술의 정답·오답 (신뢰성 지표)."""
    byq = {q.id: q for q in items}
    out = {"correct": 0, "unknown": 0, "wrong": 0, "knowledge_correct": 0, "knowledge_wrong": 0}
    for r in recs:
        q = byq.get(r["question_id"])
        if q is None or not q.statement_labels:
            continue
        for k, lab in q.statement_labels.items():
            j = (r.get("judgments") or {}).get(k)
            if not j or j["verdict"] == "unknown":
                out["unknown"] += 1
                continue
            ok = j["verdict"] == ("true" if lab else "false")
            out["correct" if ok else "wrong"] += 1
            if j.get("source") == "knowledge":
                out["knowledge_correct" if ok else "knowledge_wrong"] += 1
    return out


def _tokens(recs: list[dict]) -> dict:
    """호출 비용 비교용: 입력·출력(추론 포함) 토큰 합계와 재시도 수."""
    calls = [c for r in recs for c in r.get("llm_calls", []) + (r.get("rewrite") or {}).get("llm_calls", [])]
    tot = lambda k: sum(c.get(k) or 0 for c in calls)  # noqa: E731
    return {"calls": len(calls), "input": tot("input_tokens"), "output": tot("output_tokens"),
            "reasoning": tot("reasoning_tokens"), "retries": sum(c.get("attempt", 1) > 1 for c in calls),
            "empty_responses": sum(bool(c.get("empty")) for c in calls)}


def _git_commit() -> str | None:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None


def run_bar_eval(settings: Settings, eval_path: Path, modes: list[RetrievalMode], label: str = "",
                 meta: dict | None = None) -> Path:
    es = load_bar_evalset(eval_path)
    if es.split == "test" and not es.frozen:
        raise SystemExit("test 평가셋이 frozen=true 로 고정되지 않았습니다.")
    if es.split == "all":
        print("⚠ 시험 70문항 전체 실행: test 17문항이 포함됩니다. 이 결과는 '탐색 실행'으로만 기록하고,\n"
              "  test 문항 결과를 보고 설정·프롬프트를 바꾸지 마세요 (최종 평가는 고정된 eval/test.json 으로 별도 실행).")
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + (label or uuid.uuid4().hex[:4])
    out = settings.resolve(settings.paths.results_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)

    solver = MCQSolver(settings)
    agent = None if modes == [RetrievalMode.NONE] else KnowledgeAgent(settings, solver.retriever)
    mcq_recs: list[dict] = []
    na_recs: list[dict] = []
    with (out / "records.jsonl").open("w", encoding="utf-8") as f:
        for mode in modes:
            for q in es.items:
                r = solver.solve(q, mode, run_id)
                r["eval"] = {"kind": "mcq", "split": es.split, "version": es.version, "type": q.type,
                             "traps": q.traps,
                             "answer": q.answer, "correct": int(r.get("predicted") == q.answer),
                             "hit@5": mcq_hit_at_k(r, q), "statement_acc": statement_accuracy(r, q)}
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                mcq_recs.append(r)
                print(f"[{mode.value}] {q.id} pred={r.get('predicted')} ans={q.answer} "
                      f"status={r['status']} hit@5={r['eval']['hit@5']} {r['timing_ms'].get('total')}ms")
            for item in es.no_answer if mode != RetrievalMode.NONE else []:  # closed-book 은 선택형만
                r = agent.ask(item.question, mode=mode, question_id=item.id, run_id=run_id)
                r["eval"] = {"kind": "no_answer", "split": es.split, "version": es.version, "type": "no_answer"}
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                na_recs.append(r)
                print(f"[{mode.value}] {item.id} status={r['answer']['status']}")

    with (out / "grading.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "question_id", "config", "kind", "type", "answer", "predicted", "correct(auto)",
                    "hit@5(auto)", "status", "citation_grounded", "no_answer_handled", "grader", "reviewer", "note"])
        for r in mcq_recs:
            e = r["eval"]
            w.writerow([run_id, r["question_id"], r["config"], "mcq", e["type"], e["answer"], r.get("predicted"),
                        e["correct"], e["hit@5"], r["status"], "", "", "", "", ""])
        for r in na_recs:
            w.writerow([run_id, r["question_id"], r["config"], "no_answer", "no_answer", "", "", "", "",
                        r["answer"]["status"], "", "", "", "", ""])

    summary = {"run_id": run_id, "git_commit": _git_commit(), "run_meta": meta or {},
               "mcq_settings": settings.mcq.model_dump(), "eval": {"path": str(eval_path), "version": es.version, "split": es.split},
               "composition_warnings": check_bar_composition(es), "versions": settings.versions.model_dump(),
               "models": settings.models.model_dump(), "settings_fingerprint": settings.fingerprint(),
               "optimization": settings.optimization.model_dump(), "by_config": {}}
    for mode in modes:
        rs = [r for r in mcq_recs if r["config"] == mode.value]
        hits = [r["eval"]["hit@5"] for r in rs if r["eval"]["hit@5"] is not None]
        st_ok = sum(r["eval"]["statement_acc"][0] for r in rs)
        st_n = sum(r["eval"]["statement_acc"][1] for r in rs)
        na = [r for r in na_recs if r["config"] == mode.value]
        summary["by_config"][mode.value] = {
            "accuracy": f"{sum(r['eval']['correct'] for r in rs)}/{len(rs)}",
            "hit@5": f"{sum(hits)}/{len(hits)}" + ("" if len(hits) == len(rs) else f" (근거 미표기 {len(rs) - len(hits)}문항 제외)"),
            "statement_accuracy": f"{st_ok}/{st_n}" if st_n else None,
            "insufficient": sum(r["status"] == "insufficient_evidence" for r in rs),
            "invalid_citation": sum(r["status"] == "invalid_citation" for r in rs),
            "inconsistent_judgments": _inconsistent(rs),
            "rewrite_fallback": _rewrite_fallback(rs),
            "v5": {"asof": {str(r.get("number")): r["asof"] for r in rs if r.get("asof")},
                   "out_of_corpus": {str(r.get("number")): r["out_of_corpus"] for r in rs if r.get("out_of_corpus")},
                   "cross_refs": {str(r.get("number")): r["cross_refs"] for r in rs if r.get("cross_refs")},
                   "quote_check": {"verified": sum(v is True for r in rs for v in (r.get("quote_check") or {}).values()),
                                   "failed": sum(v is False for r in rs for v in (r.get("quote_check") or {}).values()),
                                   "no_quote": sum(v is None for r in rs for v in (r.get("quote_check") or {}).values())},
                   "calibrated": any((r.get("answer_check") or {}).get("calibrated") for r in rs)},
            "tiebreak": {"rejudged": [r.get("number") for r in rs if r.get("tiebreak")],
                         "still_tied": [r.get("number") for r in rs if r["status"] == "tie"],
                         "correct_after": sum(r["eval"]["correct"] for r in rs if r.get("tiebreak"))},
            "no_answer_insufficient_status(사람 검토 전)": f"{sum(r['answer']['status'] == 'insufficient_evidence' for r in na)}/{len(na)}",
            "latency_mcq": _latency(rs, lambda r: r["status"]),
            "llm_tokens": _tokens(rs),
            "statements": _statement_breakdown(rs, es.items),
            "latency_no_answer": _latency(na, lambda r: r["answer"]["status"]),
        }
    # 함정 유형별 정답률: 'RAG 가 어떤 함정을 막는가'
    trap_table: dict[str, dict[str, str]] = {}
    for mode in modes:
        rs = [r for r in mcq_recs if r["config"] == mode.value]
        for tag in sorted({t for r in rs for t in r["eval"]["traps"]}):
            sub = [r for r in rs if tag in r["eval"]["traps"]]
            trap_table.setdefault(tag, {})[mode.value] = f"{sum(r['eval']['correct'] for r in sub)}/{len(sub)}"
    summary["accuracy_by_trap"] = trap_table
    summary["index"] = _index_info(settings)
    summary["complete"] = True  # 끝까지 돈 실행 (중단되면 summary 자체가 없거나 이 값이 없다)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"by_config": summary["by_config"], "accuracy_by_trap": trap_table},
                     ensure_ascii=False, indent=2))
    return out


def _index_info(settings: Settings) -> dict:
    """실행에 쓴 색인 식별 정보 (팀원 색인과 같은지 비교용)."""
    try:
        info = json.loads((settings.index_path() / "index_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: info.get(k) for k in ("n_chunks", "chunk_ids_sha256", "built_at", "statute_snapshot", "case_date_to")}


def _inconsistent(rs: list[dict]) -> dict:
    """판단 조합이 어느 보기와도 맞지 않아 예비 규칙으로 고른 문항 (개선안 B-계산)."""
    xs = [r for r in rs if (r.get("answer_check") or {}).get("inconsistent")]
    return {"count": len(xs), "questions": [r.get("number") for r in xs],
            "correct": sum(r["eval"]["correct"] for r in xs),
            "flipped": {str(r.get("number")): r["answer_check"].get("flipped") for r in xs}}


def _rewrite_fallback(rs: list[dict]) -> dict:
    """쿼리 리라이트가 실패해 원래 질의(발문+진술)로 검색한 문항·진술."""
    xs = [r for r in rs if (r.get("rewrite") or {}).get("fallback_keys")]
    return {"questions": len(xs), "statements": sum(len(r["rewrite"]["fallback_keys"]) for r in xs),
            "detail": {str(r.get("number")): {"keys": r["rewrite"]["fallback_keys"], "error": r["rewrite"].get("error")}
                       for r in xs}}


def aggregate_grading(grading_csv: Path) -> dict:
    """채점 완료 grading.csv → 구성별 정답률(자동)·근거 적합(사람)·정보 부족 안내(사람)."""
    with grading_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: dict = {}
    for cfg in sorted({r["config"] for r in rows}):
        mcq = [r for r in rows if r["config"] == cfg and r["kind"] == "mcq"]
        na = [r for r in rows if r["config"] == cfg and r["kind"] == "no_answer"]

        def total(col, xs):
            return sum(int(x[col] or 0) for x in xs)

        out[cfg] = {
            "accuracy(auto)": f"{total('correct(auto)', mcq)}/{len(mcq)}",
            "citation_grounded": f"{total('citation_grounded', mcq)}/{len(mcq)}",
            "no_answer_handled": f"{total('no_answer_handled', na)}/{len(na)}",
            "ungraded": sum(x["citation_grounded"] == "" for x in mcq) + sum(x["no_answer_handled"] == "" for x in na),
        }
    return out


# ---------- 반복 실행 집계 (eval --repeat) ----------
def aggregate_runs(run_dirs: list[Path], out: Path) -> dict:
    """같은 설정을 여러 번 돌린 실행들 → 구성별 정답 수 평균·범위, 실행마다 결과가 갈린 문항."""
    per_run: list[dict] = []
    by_cfg: dict[str, list[dict[int, bool]]] = {}
    for d in run_dirs:
        recs = [json.loads(x) for x in (d / "records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        mcq = [r for r in recs if r.get("eval", {}).get("kind") == "mcq"]
        row = {"run_id": d.name}
        for cfg in sorted({r["config"] for r in mcq}):
            res = {r["number"]: bool(r["eval"]["correct"]) for r in mcq if r["config"] == cfg}
            by_cfg.setdefault(cfg, []).append(res)
            row[cfg] = sum(res.values())
        per_run.append(row)
    summary: dict = {"runs": per_run, "by_config": {}}
    for cfg, runs in by_cfg.items():
        scores = [sum(r.values()) for r in runs]
        qs = sorted(set().union(*runs))
        unstable = [n for n in qs if len({r.get(n) for r in runs}) > 1]
        summary["by_config"][cfg] = {
            "n_runs": len(runs), "n_questions": len(qs), "scores": scores,
            "mean": round(sum(scores) / len(scores), 2), "min": min(scores), "max": max(scores),
            "always_wrong": [n for n in qs if not any(r.get(n) for r in runs)],
            "unstable": {str(n): [int(r.get(n, False)) for r in runs] for n in unstable},
        }
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary_repeat.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# ---------- 기존 기록 재채점 (rescore) ----------
def rescore_run(run_dir: Path, items: dict[int, ExamQuestion] | None, cap: float = 0.95) -> dict:
    """기존 실행의 진술 판단은 그대로 두고 정답 번호 계산만 예비 규칙(choose_answer_robust)으로 다시 한다.
    LLM·검색을 다시 하지 않으므로 '계산 규칙'의 효과만 본다."""
    from kant_rag.mcq.schemas import StatementJudgment
    from kant_rag.mcq.solver import choose_answer_robust

    recs = [json.loads(x) for x in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    before = after = n = 0
    changed, inconsistent = [], []
    for r in recs:
        if r.get("eval", {}).get("kind", "mcq") != "mcq" or not r.get("judgments"):
            continue
        q = ExamQuestion(**r["question"]) if r.get("question") else (items or {}).get(r.get("number"))
        if q is None or q.answer is None:
            continue
        js = {k: StatementJudgment.model_validate(v) for k, v in r["judgments"].items()}
        new, _, info = choose_answer_robust(q, js, cap)
        n += 1
        before += r.get("predicted") == q.answer
        after += new == q.answer
        if info["inconsistent"]:
            inconsistent.append({"number": q.number, "flipped": info["flipped"]})
        if new != r.get("predicted"):
            changed.append({"number": q.number, "config": r.get("config"), "from": r.get("predicted"), "to": new,
                            "answer": q.answer})
    out = {"run_id": run_dir.name, "graded": n, "before": before, "after": after,
           "changed": changed, "inconsistent": inconsistent, "cap": cap}
    (run_dir / "rescore_fallback.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ---------- 두 실행 대응 비교 (compare) ----------
def _correct_map(run_dir: Path, items: dict[int, ExamQuestion] | None) -> dict[int, bool]:
    out = {}
    for line in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("eval", {}).get("kind", "mcq") != "mcq":
            continue
        if "eval" in r and "correct" in r["eval"]:
            out[r["number"]] = bool(r["eval"]["correct"])
        else:
            q = ExamQuestion(**r["question"]) if r.get("question") else (items or {}).get(r["number"])
            if q is not None and q.answer is not None:
                out[r["number"]] = r.get("predicted") == q.answer
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """대응 표본 정확 McNemar 양측 p (불일치 b, c 의 이항검정)."""
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def compare_runs(a: Path, b: Path, items: dict[int, ExamQuestion] | None = None) -> dict:
    """같은 문항을 푼 두 실행의 정답 교차표와 정확 McNemar p. 단일 실행 차이가 노이즈인지 본다."""
    ma, mb = _correct_map(a, items), _correct_map(b, items)
    qs = sorted(set(ma) & set(mb))
    only_a = [n for n in qs if ma[n] and not mb[n]]
    only_b = [n for n in qs if mb[n] and not ma[n]]
    return {"a": a.name, "b": b.name, "n": len(qs), "a_correct": sum(ma[n] for n in qs),
            "b_correct": sum(mb[n] for n in qs), "both": sum(ma[n] and mb[n] for n in qs),
            "neither": sum(not ma[n] and not mb[n] for n in qs), "only_a": only_a, "only_b": only_b,
            "mcnemar_p": round(mcnemar_exact(len(only_a), len(only_b)), 4)}


# ---------- 확신도 보정 표본 (calibrate) ----------
def calibration_samples(run_dirs: list[Path], items: dict[int, ExamQuestion] | None = None) -> list[tuple[str, float, bool]]:
    from kant_rag.mcq.schemas import derive_statement_labels

    out = []
    for d in run_dirs:
        for line in (d / "records.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("eval", {}).get("kind", "mcq") != "mcq" or not r.get("judgments"):
                continue
            q = ExamQuestion(**r["question"]) if r.get("question") else (items or {}).get(r.get("number"))
            if q is None or q.answer is None:
                continue
            labels = q.statement_labels or derive_statement_labels(q)
            for k, j in r["judgments"].items():
                if j["verdict"] == "unknown" or k not in labels:
                    continue
                conf = j["confidence"] / 0.5 if j.get("source") == "knowledge" else j["confidence"]  # 결합 배율 되돌림
                out.append((j.get("source", "evidence"), min(conf, 1.0), (j["verdict"] == "true") == labels[k]))
    return out


# ---------- 나중 채점 (regrade): 정답 없이 푼 실행을 정답이 들어간 문항 파일로 채점 ----------
def regrade_run(run_dir: Path, items: dict[int, ExamQuestion]) -> dict:
    """예측(predicted)은 그대로 두고 정답만 대조. 진술 단위(정답/유보/확신 오답)와 오답 목록을 regrade.json 에."""
    from kant_rag.mcq.schemas import derive_statement_labels

    recs = [json.loads(x) for x in (run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows, st = [], {"correct": 0, "unknown": 0, "wrong": 0, "confident_wrong(≥0.9)": 0}
    by_form: dict[str, list[int]] = {}
    for r in recs:
        if r.get("eval", {}).get("kind", "mcq") != "mcq":
            continue
        q = items.get(r.get("number"))
        if q is None or q.answer is None:
            continue
        ok = r.get("predicted") == q.answer
        rows.append({"number": q.number, "config": r.get("config"), "form": q.form, "predicted": r.get("predicted"),
                     "answer": q.answer, "correct": ok, "status": r.get("status")})
        by_form.setdefault(q.form, [0, 0])
        by_form[q.form][0] += ok
        by_form[q.form][1] += 1
        labels = derive_statement_labels(q)
        for k, j in (r.get("judgments") or {}).items():
            if k not in labels:
                continue
            if j["verdict"] == "unknown":
                st["unknown"] += 1
            elif (j["verdict"] == "true") == labels[k]:
                st["correct"] += 1
            else:
                st["wrong"] += 1
                st["confident_wrong(≥0.9)"] += j["confidence"] >= 0.9
    out = {"run_id": run_dir.name, "graded": len(rows), "correct": sum(x["correct"] for x in rows),
           "wrong": [x["number"] for x in rows if not x["correct"]],
           "by_form": {k: f"{a}/{b}" for k, (a, b) in by_form.items()}, "statements": st, "rows": rows}
    (run_dir / "regrade.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out

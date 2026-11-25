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
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"by_config": summary["by_config"], "accuracy_by_trap": trap_table},
                     ensure_ascii=False, indent=2))
    return out


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

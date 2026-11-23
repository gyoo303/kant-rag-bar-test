"""평가 실행: 평가셋 × 구성 → results/<run_id>/records.jsonl + grading.csv + summary.json."""

from __future__ import annotations

import csv
import json
import time
import uuid
from pathlib import Path

from kant_rag.agent import KnowledgeAgent
from kant_rag.config import Settings
from kant_rag.evaluation.dataset import check_composition, load_evalset
from kant_rag.evaluation.metrics import hit_at_k, latency_summary, retrieval_summary
from kant_rag.retrieval.pipeline import RetrievalMode

GRADING_COLUMNS = [
    "run_id", "question_id", "config", "type", "hit@5", "status",
    "answer_correct", "citation_grounded", "no_answer_handled", "grader", "reviewer", "note",
]


def run_eval(settings: Settings, eval_path: Path, modes: list[RetrievalMode], label: str = "") -> Path:
    es = load_evalset(eval_path)
    warnings = check_composition(es)
    if es.split == "test" and not es.frozen:
        raise SystemExit("test 평가셋이 frozen=true 로 고정되지 않았습니다. 버전 고정 후 실행하세요.")

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + (label or uuid.uuid4().hex[:4])
    out_dir = settings.resolve(settings.paths.results_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    agent = KnowledgeAgent(settings)
    items = {i.id: i for i in es.items}
    records: list[dict] = []
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as f:
        for mode in modes:
            for item in es.items:
                rec = agent.ask(item.question, mode=mode, question_id=item.id, run_id=run_id)
                rec["eval"] = {"split": es.split, "version": es.version, "type": item.type,
                               "hit@5": hit_at_k(rec, item) if item.type != "no_answer" else None}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                records.append(rec)
                print(f"[{mode.value}] {item.id} status={rec['answer']['status']} "
                      f"hit@5={rec['eval']['hit@5']} {rec['timing_ms'].get('total')}ms")

    # 사람 채점용 CSV (0/1 기입, 교차 검토자 기록)
    with (out_dir / "grading.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GRADING_COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow({"run_id": run_id, "question_id": r["question_id"], "config": r["config"],
                        "type": r["eval"]["type"], "hit@5": r["eval"]["hit@5"],
                        "status": r["answer"]["status"]})

    summary = {
        "run_id": run_id, "eval": {"path": str(eval_path), "version": es.version, "split": es.split},
        "composition_warnings": warnings, "versions": settings.versions.model_dump(),
        "models": settings.models.model_dump(), "settings_fingerprint": settings.fingerprint(),
        "optimization": settings.optimization.model_dump(), "by_config": {},
    }
    for mode in modes:
        recs = [r for r in records if r["config"] == mode.value]
        summary["by_config"][mode.value] = {**retrieval_summary(recs, items), **latency_summary(recs)}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["by_config"], ensure_ascii=False, indent=2))
    return out_dir


def aggregate_grading(grading_csv: Path) -> dict:
    """채점 완료된 grading.csv → 구성별 정답 충족/근거 적합(/17), 정보 부족 안내(/3)."""
    with grading_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: dict = {}
    for cfg in sorted({r["config"] for r in rows}):
        rs = [r for r in rows if r["config"] == cfg]
        ans = [r for r in rs if r["type"] != "no_answer"]
        na = [r for r in rs if r["type"] == "no_answer"]
        s = lambda col, xs: sum(int(x[col] or 0) for x in xs)  # noqa: E731
        out[cfg] = {
            "answer_correct": f"{s('answer_correct', ans)}/{len(ans)}",
            "citation_grounded": f"{s('citation_grounded', ans)}/{len(ans)}",
            "no_answer_handled": f"{s('no_answer_handled', na)}/{len(na)}",
            "ungraded": sum(1 for x in ans if x["answer_correct"] == "") + sum(1 for x in na if x["no_answer_handled"] == ""),
        }
    return out

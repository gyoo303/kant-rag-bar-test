"""고정 평가 실행 (노션 STEP 6).

results/<batch_id>/
  compare.md                 구성별 비교표 (분모 포함)
  <구성>/config.json         설정·버전 스냅샷
  <구성>/runs.jsonl          문항별 원본: 후보·점수·재정렬 전후 순위·답변·출처·시간·상태
  <구성>/scores.csv          문항별 자동 채점 + 수동 검토 칸 (utf-8-sig, 엑셀 호환)
  <구성>/summary.md          지표 합계·응답 시간·오류 수
실패·오류도 지우지 않고 그대로 남긴다.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import subprocess
from pathlib import Path

from civil_rag import config
from civil_rag.agent import RUN_CONFIGS, LegalRAG
from civil_rag.evaluation.dataset import load_eval, validate
from civil_rag.evaluation.metrics import (
    citation_auto,
    fmt_ratio,
    hit_at_k,
    no_evidence_correct,
    summarize,
    verdict_correct,
)
from civil_rag.ingest.build import MANIFEST_FILE

SCORE_FIELDS = [
    "question_id", "type", "config", "status", "expected_answer", "verdict",
    "hit_at_5", "verdict_auto", "citation_auto", "no_evidence_ok",
    "정답충족_검토", "근거적합_검토", "채점근거", "채점자", "seconds", "error",
]


def _git_state() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"commit": run("rev-parse", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}


def score_item(item: dict, rec: dict, run_config: str) -> dict:
    ans = rec["answer"]
    final = (rec.get("retrieval") or {}).get("final", [])
    has_ret = RUN_CONFIGS[run_config]["mode"] is not None
    answerable = item.get("type") != "no_evidence"
    return {
        "question_id": item["id"],
        "type": item.get("type"),
        "config": run_config,
        "status": ans["status"],
        "expected_answer": item.get("expected_answer", ""),
        "verdict": ans.get("verdict"),
        "hit_at_5": hit_at_k(final, item.get("allowed_evidence", []), config.FINAL_K) if (has_ret and answerable) else None,
        "verdict_auto": verdict_correct(item.get("expected_answer"), ans.get("verdict"), ans["status"]) if answerable else None,
        "citation_auto": citation_auto(ans) if answerable else None,
        "no_evidence_ok": no_evidence_correct(ans.get("verdict"), ans["status"]) if not answerable else None,
        "정답충족_검토": "", "근거적합_검토": "", "채점근거": "", "채점자": "",
        "seconds": round(rec["total_seconds"], 3),
        "error": ans.get("error") or "",
    }


def _summary_md(run_config: str, s: dict, meta: dict) -> str:
    lat = s["latency"]
    return "\n".join([
        f"# {run_config} — {meta['split']} ({meta['eval_version']})",
        "",
        f"- 실행: {meta['started_at']} ~ {meta['finished_at']}",
        f"- 호출 성공: {s['success']}/{s['attempts']} · 오류 {s['errors']} · timeout {s['timeouts']}",
        f"- Hit@{config.FINAL_K}: {fmt_ratio(s['hit_at_5'])}",
        f"- 정답 충족(자동 예비, OX 문항): {fmt_ratio(s['verdict_auto'])}",
        f"- 근거 적합(자동 예비, 인용 유효): {fmt_ratio(s['citation_auto'])}",
        f"- 근거 없음 대응: {fmt_ratio(s['no_evidence'])}",
        f"- 응답 시간(성공 호출): 평균 {lat['mean']}s · 중앙값 {lat['median']}s · n={lat['n']}",
        "",
        "> 자동 값은 예비 채점. 최종 정답 충족·근거 적합은 scores.csv 의 검토 칸을 팀원이 교차 채점해 확정.",
    ])


def run_eval(split: str, run_configs: list[str], limit: int = 0, tag: str = "", strict: bool = False) -> Path:
    problems = validate(split)
    if problems:
        print("평가셋 점검 경고:\n  - " + "\n  - ".join(problems))
        if strict:
            raise SystemExit("strict 모드: 평가셋 문제를 먼저 고치세요.")
    version, items = load_eval(split)
    if limit:
        items = items[:limit]
    if not items:
        raise SystemExit(f"eval/{split}.json 에 문항이 없습니다.")

    batch_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{split}" + (f"-{tag}" if tag else "")
    batch_dir = config.RESULTS_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8")) if MANIFEST_FILE.exists() else {}
    rag = LegalRAG()
    compare_rows = []

    for rc in run_configs:
        out_dir = batch_dir / rc.replace("+", "_")
        out_dir.mkdir(exist_ok=True)
        started = dt.datetime.now().isoformat(timespec="seconds")
        meta = {
            "batch_id": batch_id, "run_config": rc, "split": split, "eval_version": version,
            "n_items": len(items), "started_at": started, "settings": config.snapshot(),
            "index_manifest": manifest, "git": _git_state(),
        }
        (out_dir / "config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[{rc}] {len(items)}문항 실행 → {out_dir.relative_to(config.ROOT)}")

        rows = []
        with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as runs_f:
            for i, item in enumerate(items, 1):
                res = rag.ask(item["question"], rc)
                rec = {"question_id": item["id"], "type": item.get("type"), **res.to_record()}
                runs_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                runs_f.flush()
                row = score_item(item, rec, rc)
                rows.append(row)
                print(f"  {i:>2}/{len(items)} {item['id']} {row['status']:<11} verdict={row['verdict']} "
                      f"hit@5={row['hit_at_5']} {row['seconds']:.1f}s")

        with (out_dir / "scores.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCORE_FIELDS)
            w.writeheader()
            w.writerows(rows)
        meta["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        s = summarize(rows, has_retrieval=RUN_CONFIGS[rc]["mode"] is not None)
        (out_dir / "summary.md").write_text(_summary_md(rc, s, meta), encoding="utf-8")
        compare_rows.append((rc, s))

    lines = [
        f"# 비교 — {split} ({version}) · {batch_id}",
        "",
        f"| 구성 | Hit@{config.FINAL_K} | 정답 충족(자동) | 근거 적합(자동) | 근거 없음 | 호출 성공 | 응답시간 평균/중앙값 (n) | 오류·timeout |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rc, s in compare_rows:
        lat = s["latency"]
        lines.append(
            f"| {rc} | {fmt_ratio(s['hit_at_5'])} | {fmt_ratio(s['verdict_auto'])} | {fmt_ratio(s['citation_auto'])} "
            f"| {fmt_ratio(s['no_evidence'])} | {s['success']}/{s['attempts']} | {lat['mean']}/{lat['median']} (n={lat['n']}) "
            f"| {s['errors']}·{s['timeouts']} |"
        )
    (batch_dir / "compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\n결과: {batch_dir.relative_to(config.ROOT)}")
    return batch_dir

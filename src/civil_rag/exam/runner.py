"""시험지 풀이 실행·채점.

results/<batch_id>/
  compare.md                         구성·전략별 점수 비교
  <구성>_<전략>/config.json          설정·버전 스냅샷
  <구성>_<전략>/runs.jsonl           문항별 원본 (근거·보기별 판정·질의·시간·상태)
  <구성>_<전략>/answers.csv          문항별 예측/정답/정오 (utf-8-sig)
  <구성>_<전략>/summary.md           점수·과목별 정답률·오답 목록·응답 시간
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path

from civil_rag import config
from civil_rag.evaluation.metrics import latency_stats
from civil_rag.evaluation.runner import _git_state
from civil_rag.exam.solver import ExamSolver
from civil_rag.ingest.build import MANIFEST_FILE


def load_exam(path: Path) -> dict:
    exam = json.loads(path.read_text(encoding="utf-8"))
    for it in exam.get("items", []):
        it["choices"] = {str(k): v for k, v in it["choices"].items()}
        if len(it["choices"]) != 5:
            print(f"  ! {it.get('no')}번: 보기가 {len(it['choices'])}개")
    return exam


def _warm_up(solver: ExamSolver, run_config: str) -> None:
    """동시 실행 전에 공유 자원을 한 번만 만들어 둔다 (스레드마다 모델을 따로 불러오지 않게)."""
    from civil_rag.agent import RUN_CONFIGS
    from civil_rag.models import chat_model

    chat_model()
    mode = RUN_CONFIGS[run_config]["mode"]
    if mode is None:
        return
    r = solver.retriever
    _ = r.bm25
    _ = r.vector_store
    if mode == "C":
        from civil_rag.models import cross_encoder

        cross_encoder()


def run_exam(exam_file: Path, run_configs: list[str], strategy: str = "whole",
             limit: int = 0, numbers: list[int] | None = None, tag: str = "", workers: int = 1) -> Path:
    """workers>1 이면 문항을 동시에 풀어 LLM 응답 대기 시간을 겹친다 (점수는 같고 시간만 줄어듦)."""
    exam = load_exam(exam_file)
    exam_id = exam.get("exam_id", exam_file.stem)
    items = exam["items"]
    if numbers:
        items = [it for it in items if it["no"] in set(numbers)]
    if limit:
        items = items[:limit]
    batch_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-exam-{exam_id}" + (f"-{tag}" if tag else "")
    batch_dir = config.RESULTS_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8")) if MANIFEST_FILE.exists() else {}
    solver = ExamSolver()
    compare = []

    for rc in run_configs:
        name = f"{rc.replace('+', '_')}_{strategy}"
        out_dir = batch_dir / name
        out_dir.mkdir(exist_ok=True)
        meta = {
            "batch_id": batch_id, "exam_id": exam_id, "exam_file": str(exam_file), "run_config": rc,
            "strategy": strategy, "n_items": len(items), "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "settings": config.snapshot(), "index_manifest": manifest, "git": _git_state(),
        }
        (out_dir / "config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[{rc} · {strategy}] {exam_id} {len(items)}문항 → {out_dir.relative_to(config.ROOT)}")

        results = []
        lock = threading.Lock()
        t_start = time.perf_counter()
        with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as f:

            def record(it, r):
                with lock:
                    f.write(json.dumps({"subject": it.get("subject"), **r.to_record()}, ensure_ascii=False) + "\n")
                    f.flush()
                    results.append((it, r))
                    mark = {1: "O", 0: "X", None: "?"}[r.correct]
                    print(f"  {it['no']:>3}번 예측 {r.predicted} / 정답 {r.answer} {mark}  {r.status} {r.seconds:.1f}s"
                          f"  ({len(results)}/{len(items)})", flush=True)

            if workers <= 1:
                for it in items:
                    record(it, solver.solve(it, rc, strategy))
            else:
                _warm_up(solver, rc)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(solver.solve, it, rc, strategy): it for it in items}
                    for fut in as_completed(futures):
                        record(futures[fut], fut.result())
        results.sort(key=lambda x: x[0]["no"])
        meta["wall_seconds"] = round(time.perf_counter() - t_start, 1)
        meta["workers"] = workers
        (out_dir / "config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        with (out_dir / "answers.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["no", "subject", "predicted", "answer", "correct", "status", "polarity", "seconds", "error"])
            for it, r in results:
                w.writerow([r.no, it.get("subject", ""), r.predicted, r.answer, r.correct, r.status, r.polarity,
                            round(r.seconds, 2), r.error or ""])

        graded = [r for _, r in results if r.correct is not None]
        score = sum(r.correct for r in graded)
        by_subj: dict[str, list[int]] = defaultdict(list)
        for it, r in results:
            if r.correct is not None:
                by_subj[it.get("subject") or "-"].append(r.correct)
        ok = [r for _, r in results if r.status == "ok"]
        lat = latency_stats(r.seconds for r in ok)
        tok_in = sum((r.usage or {}).get("input_tokens", 0) for _, r in results)
        tok_out = sum((r.usage or {}).get("output_tokens", 0) for _, r in results)
        meta["tokens"] = {"input": tok_in, "output": tok_out}
        (out_dir / "config.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        wrong = [f"{r.no}번(예측 {r.predicted}/정답 {r.answer})" for _, r in results if r.correct == 0]
        errors = [r for _, r in results if r.status != "ok"]
        md = [
            f"# {exam_id} — {rc} · {strategy}",
            "",
            f"- 점수: **{score}/{len(graded)}**" + (f" ({score / len(graded):.1%})" if graded else ""),
            f"- 호출 성공: {len(ok)}/{len(results)} · 오류·timeout {len(errors)}",
            f"- 응답 시간(성공): 평균 {lat['mean']}s · 중앙값 {lat['median']}s · n={lat['n']}",
            f"- 전체 소요: {meta['wall_seconds'] / 60:.1f}분 (동시 실행 {workers}개)",
            f"- LLM 토큰: 입력 {tok_in:,} · 출력 {tok_out:,}"
            + (f" (문항당 평균 입력 {tok_in // max(len(results), 1):,})" if results else ""),
            "",
            "| 과목 | 정답 | 정답률 |",
            "|---|---|---|",
            *[f"| {s} | {sum(v)}/{len(v)} | {sum(v) / len(v):.1%} |" for s, v in sorted(by_subj.items())],
            "",
            "오답: " + (", ".join(wrong) if wrong else "없음"),
        ]
        (out_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        compare.append((name, score, len(graded), len(ok), len(results), lat))

    lines = [f"# 시험지 비교 — {exam_id} · {batch_id}", "",
             "| 구성·전략 | 점수 | 정답률 | 호출 성공 | 응답시간 평균/중앙값 (n) |", "|---|---|---|---|---|"]
    for name, s, n, ok, tot, lat in compare:
        lines.append(f"| {name} | {s}/{n} | {(s / n if n else 0):.1%} | {ok}/{tot} | {lat['mean']}/{lat['median']} (n={lat['n']}) |")
    (batch_dir / "compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines) + f"\n\n결과: {batch_dir.relative_to(config.ROOT)}")
    return batch_dir

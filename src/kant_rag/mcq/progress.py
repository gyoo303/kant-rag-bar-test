"""진행 중인 평가 실행 보기 (`kant-rag progress <label> [--watch 60]`).

results/ 에서 이름이 label 로 끝나는 가장 최근 폴더의 records.jsonl 을 읽어 문항별 예측/정답 표와 누적 정답 수를 출력합니다.
실행 중에도 읽기만 하므로 평가에 영향을 주지 않습니다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

CIRCLED = "①②③④⑤"


def latest_run(results_dir: Path, label: str) -> Path | None:
    runs = sorted(p for p in results_dir.iterdir() if p.is_dir() and p.name.endswith(label))
    return runs[-1] if runs else None


def _c(n: int | None) -> str:
    return CIRCLED[n - 1] if n and 1 <= n <= 5 else "-"


def read_records(run: Path) -> list[dict]:
    path = run / "records.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:  # 쓰는 중인 마지막 줄
            continue
        if r.get("eval", {}).get("kind", "mcq") == "mcq":
            out.append(r)
    return out


def render(run: Path, total: int | None = None) -> str:
    recs = read_records(run)
    lines = [f"{run.name}  ({datetime.now():%H:%M:%S} 확인)", "", " 문항 | 예측 | 정답 | 결과 | 시간(초)", "------+------+------+------+---------"]
    correct = graded = 0
    for r in recs:
        pred, ans = r.get("predicted"), r.get("eval", {}).get("answer")
        mark = "-" if ans is None else ("○" if pred == ans else "×")
        if ans is not None:
            graded += 1
            correct += pred == ans
        sec = (r.get("timing_ms", {}).get("total") or 0) / 1000
        lines.append(f" {r.get('number', '?'):>4} |  {_c(pred)}   |  {_c(ans)}   |  {mark}   | {sec:7.1f}")
    done = len(recs)
    head = f"진행 {done}" + (f"/{total}" if total else "") + f" · 정답 {correct}/{graded}"
    if graded:
        head += f" ({correct / graded:.0%})"
    wrong = [r.get("number") for r in recs if r.get("eval", {}).get("answer") is not None
             and r.get("predicted") != r["eval"]["answer"]]
    lines += ["", head, f"오답: {wrong}" if wrong else "오답: 없음"]
    if (run / "summary.json").exists():
        lines.append("✔ 실행 완료 (summary.json 생성됨)")
    return "\n".join(lines)


def watch(results_dir: Path, label: str, interval: int = 0, total: int | None = None) -> None:
    while True:
        run = latest_run(results_dir, label)
        text = render(run, total) if run else f"results/ 에 '{label}' 로 끝나는 폴더가 아직 없습니다."
        if interval:
            print("\033[2J\033[H", end="")  # 화면 지우기
        print(text, flush=True)
        if not interval or (run and (run / "summary.json").exists()):
            return
        time.sleep(interval)

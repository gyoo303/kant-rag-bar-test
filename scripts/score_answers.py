"""시험지 답안 채점·비교 — 팀원마다 RAG 구현이 달라도 같은 기준으로 점수를 낸다.

답안 CSV 형식 (헤더 필수, 다른 칸은 무시):  no,predicted
  - civil-rag exam 결과의 answers.csv 를 그대로 넣어도 된다.

사용:
  python -I scripts/score_answers.py exams/2026-civil-mc.json member1.csv member2.csv member3.csv
  python -I scripts/score_answers.py exams/2026-civil-mc.json results/<batch>/C_whole/answers.csv --names C
표준 라이브러리만 사용.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def load_answers(path: Path) -> dict[int, int | None]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or "no" not in rows[0] or "predicted" not in rows[0]:
        raise SystemExit(f"{path}: 'no,predicted' 헤더가 필요합니다.")
    out: dict[int, int | None] = {}
    for r in rows:
        p = (r.get("predicted") or "").strip()
        out[int(r["no"])] = int(p) if p.isdigit() else None
    return out


def band(no: int, size: int = 10) -> str:
    lo = (no - 1) // size * size + 1
    return f"{lo}-{lo + size - 1}"


def score(key: dict[int, int], ans: dict[int, int | None]) -> dict:
    correct = [n for n in key if ans.get(n) == key[n]]
    wrong = [n for n in key if ans.get(n) is not None and ans.get(n) != key[n]]
    blank = [n for n in key if ans.get(n) is None]
    bands: dict[str, list[int]] = {}
    for n in key:
        bands.setdefault(band(n), []).append(int(ans.get(n) == key[n]))
    return {"score": len(correct), "total": len(key), "wrong": wrong, "blank": blank,
            "bands": {k: (sum(v), len(v)) for k, v in bands.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("exam_json")
    ap.add_argument("answers", nargs="+", help="답안 CSV (여러 개면 비교표)")
    ap.add_argument("--names", nargs="*", default=None, help="표에 쓸 이름 (답안 순서대로)")
    a = ap.parse_args(argv)

    exam = json.loads(Path(a.exam_json).read_text(encoding="utf-8"))
    key = {it["no"]: it["answer"] for it in exam["items"] if it.get("answer")}
    names = a.names or [Path(p).parent.name if Path(p).name == "answers.csv" else Path(p).stem for p in a.answers]
    results = [(n, score(key, load_answers(Path(p)))) for n, p in zip(names, a.answers)]

    bands = list(results[0][1]["bands"])
    print(f"# {exam.get('title') or exam.get('exam_id')} — 정답 {len(key)}문항\n")
    print("| 답안 | 점수 | 정답률 | " + " | ".join(bands) + " | 미응답 |")
    print("|---|---|---|" + "---|" * len(bands) + "---|")
    for n, s in results:
        cells = " | ".join(f"{s['bands'][b][0]}/{s['bands'][b][1]}" for b in bands)
        print(f"| {n} | {s['score']}/{s['total']} | {s['score'] / s['total']:.1%} | {cells} | {len(s['blank'])} |")
    print()
    for n, s in results:
        print(f"- {n} 오답: {', '.join(map(str, s['wrong'])) or '없음'}")
    if len(results) > 1:
        all_wrong = set.intersection(*(set(s["wrong"]) | set(s["blank"]) for _, s in results))
        print(f"- 모두 틀린 문항: {', '.join(map(str, sorted(all_wrong))) or '없음'}")


if __name__ == "__main__":
    main()

"""실행 기록(exam_run.jsonl)을 공식 가답안(DOC-05)으로 채점한다.

평가 무결성(C-09): 정답표는 **이 스크립트에서만** 읽는다. 풀이(run_exam.py)는 정답을 보지 않았다.
사용: python grade_exam.py <run.jsonl> <items.json>
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

KEY = Path("law_collector/data/test/2026-bar-exam-civil-mcq-answer-key.md")
KEY_LINE = re.compile(r"^(\d{1,2}),([1-5])$")


def load_key() -> dict[int, int]:
    key: dict[int, int] = {}
    for line in KEY.read_text(encoding="utf-8").splitlines():
        m = KEY_LINE.match(line.strip())
        if m:
            key[int(m.group(1))] = int(m.group(2))
    return key


def picked(record: dict) -> int | None:
    """고른 번호. 도메인 규칙(INV-13)에 걸려 answer_no가 비어도 모델이 고른 번호를 살린다.

    이번 시험 한정 채점 기준: "번호만 맞으면 정답". 저장소 규칙은 바꾸지 않았다.
    """
    if record.get("answer_no") in (1, 2, 3, 4, 5):
        return record["answer_no"]
    raw = record.get("raw_output")
    if not raw:
        return None
    try:
        value = json.loads(raw).get("answer")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if value in (1, 2, 3, 4, 5) else None


def main() -> int:
    runs = [json.loads(ln) for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if ln.strip()]
    items = {i["no"]: i for i in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))}
    key = load_key()
    combo = {no for no, it in items.items() if re.search(r"^ㄱ\.", it["stem"], re.M)}

    outcomes = Counter(r["outcome"] for r in runs)
    for r in runs:
        r["_pick"] = picked(r)
    attempted = [r for r in runs if r["_pick"] is not None]
    correct = [r for r in attempted if r["_pick"] == key.get(r["no"])]
    wrong = [r for r in attempted if r["_pick"] != key.get(r["no"])]
    strict_ok = [r for r in runs if r.get("answer_no") == key.get(r["no"])]

    print(f"채점 대상 {len(runs)}문항 / 정답표 {len(key)}문항")
    print()
    print("== 결과 종류 (저장소 규칙 그대로, 내부 기록용) ==")
    for name, n in outcomes.most_common():
        print(f"  {name:22s} {n:3d}  ({n / len(runs) * 100:.1f}%)")
    print(f"  저장소 규칙으로 정답 처리된 문항: {len(strict_ok)} "
          f"({len(strict_ok) / len(runs) * 100:.1f}%)")
    print()
    print("== 정답률 (이번 시험 기준: 번호만 맞으면 정답) ==")
    print(f"  번호를 고른 문항  {len(attempted):3d} / {len(runs)}")
    if attempted:
        print(f"  그중 정답         {len(correct):3d}  (고른 것 기준 {len(correct) / len(attempted) * 100:.1f}%)")
    print(f"  전체 기준 정답률  {len(correct) / len(runs) * 100:.1f}%  (무응답을 오답으로)")
    print("  찍기 기댓값       20.0%")
    print()

    print("== 유형별 ==")
    for label, nos in (("조합형(ㄱㄴㄷ)", combo), ("일반형", set(items) - combo)):
        sub = [r for r in runs if r["no"] in nos]
        sub_att = [r for r in sub if r["_pick"] is not None]
        sub_cor = [r for r in sub_att if r["_pick"] == key.get(r["no"])]
        rate = f"{len(sub_cor) / len(sub) * 100:.1f}%" if sub else "-"
        print(f"  {label:16s} {len(sub):2d}문항  고름 {len(sub_att):2d}  정답 {len(sub_cor):2d}  ({rate})")
    print()

    print("== 맞힌 문항 ==")
    print("  " + (", ".join(str(r["no"]) for r in sorted(correct, key=lambda r: r["no"])) or "없음"))
    print("== 틀린 문항 (정답/선택) ==")
    print("  " + (", ".join(f"{r['no']}({key.get(r['no'])}/{r['_pick']})"
                            for r in sorted(wrong, key=lambda r: r["no"])) or "없음"))
    no_pick = [r["no"] for r in runs if r["_pick"] is None]
    print("== 번호를 못 고른 문항 ==")
    print("  " + (", ".join(map(str, sorted(no_pick))) or "없음"))
    print()

    errs = Counter(r.get("error_code") for r in runs if r.get("error_code"))
    if errs:
        print("== 오류 코드 ==")
        for code, n in errs.most_common():
            print(f"  {code:24s} {n}")
        print()

    lat = [r["latency_ms"] for r in runs if r.get("latency_ms")]
    ctx = [r.get("context_count", 0) for r in runs]
    if lat:
        lat_sorted = sorted(lat)
        print("== 성능 ==")
        print(f"  응답 시간 중앙값 {lat_sorted[len(lat) // 2] / 1000:.1f}초, "
              f"최대 {max(lat) / 1000:.1f}초, 합계 {sum(lat) / 60000:.1f}분")
        print(f"  문항당 검색 후보 평균 {sum(ctx) / len(ctx):.1f}개")

    out = Path(sys.argv[1]).with_name("graded.json")
    out.write_text(json.dumps(
        [{"no": r["no"], "outcome": r["outcome"], "picked": r["_pick"],
          "answer_no_strict": r.get("answer_no"),
          "key": key.get(r["no"]), "ok": r["_pick"] == key.get(r["no"]),
          "combo": r["no"] in combo} for r in sorted(runs, key=lambda r: r["no"])],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n문항별 표: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

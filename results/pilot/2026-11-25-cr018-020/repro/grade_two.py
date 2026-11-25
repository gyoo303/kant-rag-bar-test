"""CR-014 이후 채점: 지표 2종을 나눠 낸다.

- **정답 충족(번호)**: 고른 번호가 정답이면 1
- **근거 충족 정답**: 번호도 맞고 `evidence_sufficient=true`여야 1

평가 무결성(C-09): 정답표는 이 스크립트에서만 읽는다.
사용: python grade_two.py <run.jsonl> <items.json> [before_graded.json]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

KEY = Path("docs/00-inputs/2026-bar-exam-civil-mcq-answer-key.md")
KEY_LINE = re.compile(r"^(\d{1,2}),([1-5])$")


def load_key() -> dict[int, int]:
    key: dict[int, int] = {}
    for line in KEY.read_text(encoding="utf-8").splitlines():
        m = KEY_LINE.match(line.strip())
        if m:
            key[int(m.group(1))] = int(m.group(2))
    return key


def picked(r: dict) -> int | None:
    if r.get("answer_no") in (1, 2, 3, 4, 5):
        return r["answer_no"]
    try:
        v = json.loads(r.get("raw_output") or "").get("answer")
    except (json.JSONDecodeError, AttributeError):
        return None
    return v if v in (1, 2, 3, 4, 5) else None


def pct(n: int, d: int) -> str:
    return f"{n / d * 100:.1f}%" if d else "-"


def main() -> int:
    runs = [
        json.loads(ln)
        for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    items = {i["no"]: i for i in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))}
    key = load_key()
    combo = {no for no, it in items.items() if re.search(r"^ㄱ\.", it["stem"], re.M)}
    n = len(runs)

    rows = []
    for r in sorted(runs, key=lambda r: r["no"]):
        p = picked(r)
        suf = bool(r.get("evidence_sufficient"))
        ok = p == key.get(r["no"])
        rows.append(
            {
                "no": r["no"],
                "outcome": r["outcome"],
                "picked": p,
                "key": key.get(r["no"]),
                "answer_correct": int(ok),
                "evidence_sufficient": suf,
                "confident_correct": int(ok and suf),
                "combo": r["no"] in combo,
            }
        )

    ac = sum(x["answer_correct"] for x in rows)
    cc = sum(x["confident_correct"] for x in rows)
    suf_n = sum(x["evidence_sufficient"] for x in rows)

    print(f"채점 {n}문항 / 정답표 {len(key)}문항\n")
    print("== 결과 종류 ==")
    for name, c in Counter(x["outcome"] for x in rows).most_common():
        print(f"  {name:22s} {c:3d}  ({pct(c, n)})")
    print()
    print("== 지표 2종 (CR-014) ==")
    print(f"  ① 정답 충족(번호)      {ac:3d}/{n}  {pct(ac, n)}")
    print(f"  ② 근거 충족 정답        {cc:3d}/{n}  {pct(cc, n)}")
    print(f"     격차(①-②)           {ac - cc:3d}문항  — 맞혔지만 근거를 못 댄 문항")
    print(f"  근거 충족이라 표시한 문항 {suf_n:3d}/{n}  {pct(suf_n, n)}")
    print()

    print("== 근거 충족 여부 × 정답 (신호 변별력) ==")
    for label, want in (("근거 충족", True), ("근거 부족", False)):
        sub = [x for x in rows if x["evidence_sufficient"] is want]
        okn = sum(x["answer_correct"] for x in sub)
        print(f"  {label}  {len(sub):3d}문항 중 정답 {okn:3d}  ({pct(okn, len(sub))})")
    print()

    print("== 유형별 ==")
    for label, want in (("조합형(ㄱㄴㄷ)", True), ("일반형", False)):
        sub = [x for x in rows if x["combo"] is want]
        a = sum(x["answer_correct"] for x in sub)
        c = sum(x["confident_correct"] for x in sub)
        print(f"  {label:16s} {len(sub):2d}문항  ①{a:3d} ({pct(a, len(sub))})  ②{c:3d} ({pct(c, len(sub))})")
    print()

    wrong = [x for x in rows if not x["answer_correct"]]
    print("== 틀린 문항 (정답/선택, 근거) ==")
    print(
        "  "
        + (
            ", ".join(
                f"{x['no']}({x['key']}/{x['picked']},{'충족' if x['evidence_sufficient'] else '부족'})"
                for x in wrong
            )
            or "없음"
        )
    )

    if len(sys.argv) > 3 and Path(sys.argv[3]).is_file():
        before = {b["no"]: b for b in json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))}
        b_ok = sum(1 for b in before.values() if b["ok"])
        print()
        print("== 이전 실행과 비교 (둘 다 '번호만 맞으면 정답' 기준) ==")
        print(f"  이전  {b_ok}/{len(before)}  {pct(b_ok, len(before))}")
        print(f"  이후  {ac}/{n}  {pct(ac, n)}")
        gained = [x["no"] for x in rows if x["answer_correct"] and not before.get(x["no"], {}).get("ok")]
        lost = [x["no"] for x in rows if not x["answer_correct"] and before.get(x["no"], {}).get("ok")]
        print(f"  새로 맞힌 문항: {gained or '없음'}")
        print(f"  새로 틀린 문항: {lost or '없음'}")

    out = Path(sys.argv[1]).with_name("graded_two.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n문항별 표: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

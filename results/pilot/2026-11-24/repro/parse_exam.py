"""DOC-04(2026 선택형 민사법 문제지 텍스트 추출본)를 70문항으로 나눈다.

평가 무결성(C-09): 이 스크립트는 **문제지만** 읽는다. 정답표(DOC-05)는 절대 열지 않는다.
출력: items.json = [{"no": 1, "stem": "...", "options": [5개]}, ...]

보기는 PDF가 2단 배치라 `① ㄱ, ㄷ  ② ㄱ, ㄴ, ㄷ`처럼 한 줄에 둘씩 오기도 한다.
그래서 줄 머리가 아니라 **본문 전체에서 ①~⑤ 표시 위치**로 자른다.
지문 안에도 ① 같은 글자가 나올 수 있으므로, 마지막으로 나타나는 ①②③④⑤ 오름차순 묶음만 보기로 본다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EXAM = Path("docs/00-inputs/2026-bar-exam-civil-mcq.txt")
QUESTION_HEAD = re.compile(r"^문\s*(\d+)\.\s*$")
PAGE_MARK = re.compile(r"^\d+쪽$")
MARK = re.compile(r"[①②③④⑤]")
CIRCLED = "①②③④⑤"


def _clean(line: str) -> str:
    return line.replace("\xa0", " ").strip()


def _split_options(body: str) -> tuple[str, list[str]] | None:
    """본문을 (지문, 보기 5개)로 자른다. 보기 묶음을 못 찾으면 None."""
    marks = list(MARK.finditer(body))
    # 뒤에서부터 ①②③④⑤ 오름차순 5개가 연속으로 나오는 자리를 찾는다
    for start in range(len(marks) - 5, -1, -1):
        run = marks[start : start + 5]
        if [m.group() for m in run] == list(CIRCLED):
            stem = body[: run[0].start()]
            options = []
            for pos, mark in enumerate(run):
                end = run[pos + 1].start() if pos + 1 < 5 else len(body)
                options.append(body[mark.end() : end])
            cleaned = [re.sub(r"\s+", " ", o).strip() for o in options]
            # 마지막 보기 뒤에 붙는 문제지 꼬리말 제거
            cleaned[-1] = re.sub(r"\s*이하부터는\s*여백입니다\.?\s*$", "", cleaned[-1]).strip()
            return stem.strip(), cleaned
    return None


def parse(text: str) -> list[dict]:
    lines = [_clean(ln) for ln in text.splitlines()]
    starts = [i for i, ln in enumerate(lines) if QUESTION_HEAD.match(ln)]
    if not starts:
        raise SystemExit("문항 머리를 찾지 못했습니다.")

    items: list[dict] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        no = int(QUESTION_HEAD.match(lines[start]).group(1))
        body = "\n".join(ln for ln in lines[start + 1 : end] if ln and not PAGE_MARK.match(ln))
        split = _split_options(body)
        if split is None:
            items.append({"no": no, "stem": body.strip(), "options": [], "error": "보기 5개 못 찾음"})
            continue
        stem, options = split
        items.append({"no": no, "stem": stem, "options": options})
    return items


def main() -> int:
    items = parse(EXAM.read_text(encoding="utf-8"))
    bad = []
    for it in items:
        if it.get("error"):
            bad.append((it["no"], it["error"]))
            continue
        if not it["stem"]:
            bad.append((it["no"], "지문 없음"))
        empty = [i + 1 for i, o in enumerate(it["options"]) if not o]
        if empty:
            bad.append((it["no"], f"빈 보기 {empty}"))

    print(f"items={len(items)} range={items[0]['no']}-{items[-1]['no']}")
    missing = sorted(set(range(1, 71)) - {it["no"] for it in items})
    print(f"missing={missing}")
    print(f"bad={len(bad)}")
    for no, why in bad[:20]:
        print(f"  Q{no}: {why}")
    ok = [i for i in items if not i.get("error")]
    print(f"stem_max={max(len(i['stem']) for i in ok):,} option_max="
          f"{max(len(o) for i in ok for o in i['options']):,}")

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("items.json")
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""법무부 문서뷰어(viewer.moj.go.kr) 시험지 쪽 HTML → exams/<exam_id>.json

사용:
  python -I scripts/parse_moj_exam.py exams/raw/2026-civil exams/2026-civil-mc.json --exam-id 2026-civil-mc \
      --title "2026년 변호사시험 민사법 선택형"
쪽 파일(1.html, 2.html, …)은 뷰어의 <파일>.files/<n>.html 을 그대로 받은 것.
정답은 --answers "1:3,2:5,..." 또는 나중에 JSON 의 answer 칸에 채운다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

CIRCLED = "①②③④⑤"
Q_HEAD = re.compile(r"^문\s*(\d{1,3})\s*\.\s*(.*)$")
CHOICE = re.compile(r"^([①②③④⑤])\s*(.*)$")
PAGE_MARK = re.compile(r"^(\d+\s*쪽|-\s*\d+\s*-|\d+\s*/\s*\d+)$")
SUBJECT_HEAD = re.compile(r"^(민\s*사\s*법|민\s*법|상\s*법|민\s*사\s*소\s*송\s*법)$")


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def page_text(path: Path) -> str:
    raw = path.read_bytes()
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
    enc = m.group(1).decode() if m else "utf-8"
    p = _Text()
    p.feed(raw.decode(enc, errors="replace"))
    return "".join(p.parts)


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.replace("\xa0", " ").replace("　", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = line.replace("｢", "「").replace("｣", "」")
        line = re.sub(r"\s*이하부터는\s*여백입니다\.?\s*$", "", line)
        if not line or PAGE_MARK.match(line):
            continue
        # "① ㄱ, ㄷ ② ㄱ, ㄴ, ㄷ" 처럼 한 줄에 보기가 여러 개면 나눈다
        if line[0] in CIRCLED and sum(ch in CIRCLED for ch in line) > 1:
            out.extend(s.strip() for s in re.split(r"(?=[①②③④⑤])", line) if s.strip())
            continue
        out.append(line)
    return out


def parse(lines: list[str]) -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    subject = None
    for line in lines:
        if SUBJECT_HEAD.match(line.replace(" ", "")) or SUBJECT_HEAD.match(line):
            subject = line.replace(" ", "")
            continue
        m = Q_HEAD.match(line)
        if m and (cur is None or int(m.group(1)) == cur["no"] + 1 or not items):
            if cur:
                items.append(cur)
            cur = {"no": int(m.group(1)), "subject": subject, "stem": m.group(2).strip(),
                   "passage_lines": [], "choices": {}, "_last": "stem"}
            continue
        if cur is None:
            continue
        c = CHOICE.match(line)
        if c:
            k = str(CIRCLED.index(c.group(1)) + 1)
            cur["choices"][k] = c.group(2).strip()
            cur["_last"] = k
            continue
        # 이어지는 줄: 마지막으로 쓰던 곳에 붙인다
        last = cur["_last"]
        if last == "stem" and not cur["stem"]:
            cur["stem"] = line
        elif last == "stem" and not re.match(r"^[ㄱ-ㅎ]\.|^<|^〈|^\[", line) and not cur["passage_lines"] \
                and not cur["stem"].endswith(("?", ")", "？")):
            cur["stem"] += " " + line
        elif last in cur["choices"]:
            cur["choices"][last] += " " + line
        else:
            cur["passage_lines"].append(line)
            cur["_last"] = "passage"
    if cur:
        items.append(cur)

    out = []
    for it in items:
        passage = "\n".join(it.pop("passage_lines"))
        it.pop("_last")
        if passage:
            it["passage"] = passage
        out.append(it)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pages_dir", help="뷰어 쪽 HTML 폴더 또는 PDF 에서 뽑은 .txt 파일")
    ap.add_argument("out_json")
    ap.add_argument("--exam-id", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--subject", default=None, help="과목 머리말이 없을 때 기본 과목")
    ap.add_argument("--answers", default="", help='"1:3,2:5,..."')
    a = ap.parse_args(argv)

    src = Path(a.pages_dir)
    lines: list[str] = []
    if src.is_file():  # PDF 에서 뽑은 텍스트 파일 (예: exams/raw/2025-civil/exam.txt)
        lines = clean_lines(src.read_text(encoding="utf-8"))
    else:              # 법무부 뷰어 쪽 HTML 폴더
        pages = sorted(src.glob("*.html"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
        for p in pages:
            lines.extend(clean_lines(page_text(p)))
    items = parse(lines)
    answers = {int(k): int(v) for k, v in (x.split(":") for x in a.answers.split(",") if ":" in x)}
    for it in items:
        it["subject"] = it.get("subject") or a.subject
        if it["no"] in answers:
            it["answer"] = answers[it["no"]]
    exam = {"exam_id": a.exam_id, "title": a.title, "source": "법무부 공개 (viewer.moj.go.kr)", "items": items}
    Path(a.out_json).write_text(json.dumps(exam, ensure_ascii=False, indent=2), encoding="utf-8")

    bad = [it["no"] for it in items if len(it["choices"]) != 5]
    nos = [it["no"] for it in items]
    missing = sorted(set(range(1, max(nos) + 1)) - set(nos)) if nos else []
    print(f"문항 {len(items)}개 (번호 {nos[:1]}~{nos[-1:]}) → {a.out_json}", file=sys.stderr)
    if bad:
        print(f"  ! 보기 5개가 아닌 문항: {bad}", file=sys.stderr)
    if missing:
        print(f"  ! 빠진 번호: {missing}", file=sys.stderr)


if __name__ == "__main__":
    main()

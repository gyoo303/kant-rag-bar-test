"""시험지 텍스트 → ExamQuestion 목록.

변호사시험 선택형 시험지는 `문 1.`(2026 민사법 시험지) 또는 `【문 1】` 로 문항이 시작하고, 보기는 ①~⑤, 조합형 진술은 ㄱ.~ㅁ. 형식입니다.
PDF 텍스트 추출 결과는 줄바꿈이 불규칙하므로 파싱 후 반드시 원본과 대조·수정하세요.
"""

from __future__ import annotations

import re

from kant_rag.mcq.schemas import CIRCLED, ExamQuestion

# `【문 1】` 또는 행 시작의 `문 1.` (행 중간의 '문 1.' 은 지문 일부일 수 있어 행 시작만 인정)
Q_START = re.compile(r"[【\[]\s*문\s*(\d+)\s*[】\]]|^[ \t]*문[ \t]*(\d+)[ \t]*[.．]", re.M)
OPTION = re.compile(r"([①②③④⑤])")
ITEM = re.compile(r"(?:^|\s)([ㄱㄴㄷㄹㅁㅂ])\s*[.．]\s*")
COMBO_ONLY = re.compile(r"^[\sㄱ-ㅂ,，·ㆍ]+$")
COUNT_ONLY = re.compile(r"^\s*(?:\d+|[영일이삼사오육])\s*개\s*$")  # 개수형 보기: '0개', '3개'



def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# 페이지 머리/꼬리 잡음: '1쪽', '- 3 -', 과목 표제 '민 사 법'
NOISE = re.compile(r"^[ \t]*(?:\d+[ \t]*쪽|-[ \t]*\d+[ \t]*-|민[ \t]*사[ \t]*법|이하부터는[ \t]*여백입니다\.?)[ \t]*$", re.M)
# ○× 조합형 보기: 'ㄱ(○), ㄴ(×), …'
OX_PAIR = re.compile(r"([ㄱㄴㄷㄹㅁㅂ])\s*\(\s*([○×Ｏ✕xXoO])\s*\)")
OX_ONLY = re.compile(r"^(?:\s*[ㄱㄴㄷㄹㅁㅂ]\s*\(\s*[○×Ｏ✕xXoO]\s*\)\s*[,，]?)+\s*$")


def _split_options(block: str, raw: bool = False):
    """보기 ①~⑤ 분리. 발문 안의 ①② (계약서 조항·법조문 항 번호 등)를 보기로 오인하지 않도록
    ①②③④⑤ 가 차례로 이어지는 마지막 묶음만 보기로 본다."""
    marks = list(OPTION.finditer(block))
    start = None
    for i in range(len(marks) - 4, -1, -1):
        if [m.group(1) for m in marks[i:i + 5]] == list(CIRCLED[:5]):
            start = i
            break
    if start is None:  # 보기 5개가 온전하지 않음 → 기존 방식 (검증에서 걸러짐)
        pieces = OPTION.split(block)
        head, opts = pieces[0], pieces[1:]
        out = {CIRCLED.index(opts[j]) + 1: _norm(opts[j + 1]) for j in range(0, len(opts) - 1, 2)}
        rawd = {CIRCLED.index(opts[j]) + 1: opts[j + 1] for j in range(0, len(opts) - 1, 2)}
        return (head, out, rawd) if raw else (head, out)
    sel = marks[start:start + 5]
    head = block[: sel[0].start()]
    options, rawd = {}, {}
    for k, m in enumerate(sel):
        end = sel[k + 1].start() if k + 1 < len(sel) else len(block)
        rawd[k + 1] = block[m.end(): end]
        options[k + 1] = _norm(rawd[k + 1])
    return (head, options, rawd) if raw else (head, options)


BLANK = re.compile(r"\(\s*([A-H])\s*\)")
BLANK_HEADER = re.compile(r"\s+[A-H](?:\s+[A-H])+\s*$")
COUNT_OTHER = ("알 수 없음", "없음", "판단할 수 없음", "정답 없음")


def _parse_blanks(stem: str, items: dict[str, str], raw_options: dict[int, str]):
    """괄호 넣기형: 진술 속 ( A )… 빈칸과, 보기마다 빈칸 순서대로 두 칸 이상 공백으로 나뉜 값.
    성공하면 (blank_items {A: ㄱ}, blanks {1: {A: 값}}), 아니면 None."""
    if not any(k in stem for k in ("괄호", "들어갈", "빈칸")):
        return None
    blank_items: dict[str, str] = {}
    for key, text in items.items():
        for letter in BLANK.findall(text):
            blank_items.setdefault(letter, key)
    letters = sorted(blank_items)
    if not letters:
        return None
    blanks: dict[int, dict[str, str]] = {}
    for n, raw in raw_options.items():
        vals = [v for v in re.split(r"\s{2,}|\t+", raw.strip()) if v.strip()]
        if len(vals) != len(letters):
            return None
        blanks[n] = {ltr: _norm(v) for ltr, v in zip(letters, vals)}
    return blank_items, blanks


# 한글 문서 변환 때 섞이는 다른 원문자(➀~➄ 딩뱃, ❶~❺ 검은 원문자)를 보기 번호 ①~⑤ 로
ALT_CIRCLED = str.maketrans({**{chr(0x2780 + i): "①②③④⑤"[i] for i in range(5)},
                             **{chr(0x2776 + i): "①②③④⑤"[i] for i in range(5)}})


def parse_exam_text(text: str, id_prefix: str, subject: str | None = None) -> list[ExamQuestion]:
    text = NOISE.sub("", text.translate(ALT_CIRCLED))
    starts = list(Q_START.finditer(text))
    out: list[ExamQuestion] = []
    for i, m in enumerate(starts):
        number = int(m.group(1) or m.group(2))
        block = text[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        head, options, raw_options = _split_options(block, raw=True)

        items: dict[str, str] = {}
        stem = head
        item_marks = list(ITEM.finditer(head))
        if len(item_marks) >= 2:
            stem = head[: item_marks[0].start()]
            for k, im in enumerate(item_marks):
                end = item_marks[k + 1].start() if k + 1 < len(item_marks) else len(head)
                items[im.group(1)] = _norm(head[im.end(): end])
        if items:  # 괄호 넣기형 표 머리(A B C D)가 마지막 진술에 붙은 경우 제거
            last = list(items)[-1]
            items[last] = BLANK_HEADER.sub("", items[last])
        blank = _parse_blanks(stem, items, raw_options) if items else None
        # 조합형인데 보기가 'ㄱ, ㄴ' 같은 조합만 있는지 확인 (아니면 ㄱㄴ 은 지문 일부로 간주)
        count_ok = all(COUNT_ONLY.match(v) or v in COUNT_OTHER for v in options.values()) and \
            sum(bool(COUNT_ONLY.match(v)) for v in options.values()) >= 4
        if items and not blank and not count_ok and \
                not all(COMBO_ONLY.match(v) or OX_ONLY.match(v) for v in options.values()):
            items, stem = {}, head

        out.append(ExamQuestion(id=f"{id_prefix}-{number:03d}", number=number, subject=subject,
                                stem=_norm(stem), items=items, options=options,
                                blanks=blank[1] if blank else {}, blank_items=blank[0] if blank else {}))
    return out


def parse_combo(option_text: str) -> set[str]:
    """'ㄱ, ㄷ, ㅁ' → {'ㄱ','ㄷ','ㅁ'}"""
    return set(re.findall(r"[ㄱㄴㄷㄹㅁㅂ]", option_text))


def parse_ox(option_text: str) -> dict[str, bool]:
    """'ㄱ(○), ㄴ(×)' → {'ㄱ': True, 'ㄴ': False}"""
    return {k: v in "○ＯoO" for k, v in OX_PAIR.findall(option_text)}

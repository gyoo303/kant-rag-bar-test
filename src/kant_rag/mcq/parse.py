"""시험지 텍스트 → ExamQuestion 목록.

변호사시험 선택형 시험지는 보통 `【문 1】` 로 문항이 시작하고, 보기는 ①~⑤, 조합형 진술은 ㄱ.~ㅁ. 형식입니다.
PDF 텍스트 추출 결과는 줄바꿈이 불규칙하므로 파싱 후 반드시 원본과 대조·수정하세요.
"""

from __future__ import annotations

import re

from kant_rag.mcq.schemas import CIRCLED, ExamQuestion

Q_START = re.compile(r"[【\[]\s*문\s*(\d+)\s*[】\]]")
OPTION = re.compile(r"([①②③④⑤])")
ITEM = re.compile(r"(?:^|\s)([ㄱㄴㄷㄹㅁㅂ])\s*[.．]\s*")
COMBO_ONLY = re.compile(r"^[\sㄱ-ㅂ,，·ㆍ]+$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_exam_text(text: str, id_prefix: str, subject: str | None = None) -> list[ExamQuestion]:
    starts = list(Q_START.finditer(text))
    out: list[ExamQuestion] = []
    for i, m in enumerate(starts):
        number = int(m.group(1))
        block = text[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        pieces = OPTION.split(block)
        head, opts = pieces[0], pieces[1:]
        options = {CIRCLED.index(opts[j]) + 1: _norm(opts[j + 1]) for j in range(0, len(opts) - 1, 2)}

        items: dict[str, str] = {}
        stem = head
        item_marks = list(ITEM.finditer(head))
        if len(item_marks) >= 2:
            stem = head[: item_marks[0].start()]
            for k, im in enumerate(item_marks):
                end = item_marks[k + 1].start() if k + 1 < len(item_marks) else len(head)
                items[im.group(1)] = _norm(head[im.end(): end])
        # 조합형인데 보기가 'ㄱ, ㄴ' 같은 조합만 있는지 확인 (아니면 ㄱㄴ 은 지문 일부로 간주)
        if items and not all(COMBO_ONLY.match(v) for v in options.values()):
            items, stem = {}, head

        out.append(ExamQuestion(id=f"{id_prefix}-{number:03d}", number=number, subject=subject,
                                stem=_norm(stem), items=items, options=options))
    return out


def parse_combo(option_text: str) -> set[str]:
    """'ㄱ, ㄷ, ㅁ' → {'ㄱ','ㄷ','ㅁ'}"""
    return set(re.findall(r"[ㄱㄴㄷㄹㅁㅂ]", option_text))

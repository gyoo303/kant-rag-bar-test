"""원문 텍스트 정제 (ADR-015). 순수 함수, 표준 라이브러리만 사용."""

from __future__ import annotations

import html
import re

_BREAK_TAGS = re.compile(r"<\s*(?:br|p)\s*/?\s*>|<\s*/\s*p\s*>", re.IGNORECASE)
_OTHER_TAGS = re.compile(r"<[^>]+>")
_TRAILING_SPACE = re.compile(r"[ \t ]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")


def clean_text(value: str | None) -> str:
    """HTML 태그를 지우고 줄바꿈·공백을 정리한다.

    `<br>`·`<br/>`·`<p>`는 줄바꿈으로 바꾸고, 그 밖의 태그는 지우고, HTML 엔티티를 풀고,
    줄 끝 공백을 지우고, 빈 줄이 여러 개 이어지면 1개로 줄인다. 없으면 빈 문자열.
    """
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _BREAK_TAGS.sub("\n", text)
    text = _OTHER_TAGS.sub("", text)
    text = html.unescape(text)
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()

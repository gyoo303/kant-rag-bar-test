"""BM25 토크나이저. 기본(simple)은 의존성 없는 정규식 + 한글 2-gram."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

_TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")


def simple_tokenize(text: str) -> list[str]:
    """영문/숫자는 단어 단위, 한글 어절은 어절 + 문자 2-gram (조사 붙은 어절 매칭 보완)."""
    tokens: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        tokens.append(tok)
        if "가" <= tok[0] <= "힣" and len(tok) > 2:
            tokens.extend(tok[i : i + 2] for i in range(len(tok) - 1))
    return tokens


@lru_cache
def _kiwi():
    from kiwipiepy import Kiwi

    return Kiwi()


def kiwi_tokenize(text: str) -> list[str]:
    keep = ("NN", "VV", "VA", "SL", "SN", "XR")
    return [t.form.lower() for t in _kiwi().tokenize(text) if t.tag.startswith(keep)]


def get_tokenizer(name: str) -> Callable[[str], list[str]]:
    return {"simple": simple_tokenize, "kiwi": kiwi_tokenize}[name]

"""BM25 토큰화.

- whitespace: 교안 5-1 방식 (lambda t: t.split()) — 기본값
- kiwi      : 형태소 분석 (조사 분리). 교안 밖 비교 실험용. `uv add kiwipiepy` 필요
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

_PUNCT = re.compile(r"[\[\]()【】「」『』<>.,;:·\"'“”‘’!?|]")


def whitespace_tokenize(text: str) -> list[str]:
    # 교안은 t.split(). 괄호·문장부호만 떼어 "[1]", "제750조," 같은 토큰이 갈라지지 않게 보정.
    return _PUNCT.sub(" ", text).split()


@lru_cache(maxsize=1)
def _kiwi():
    try:
        from kiwipiepy import Kiwi
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("BM25_TOKENIZER=kiwi 를 쓰려면 `uv add kiwipiepy` 가 필요합니다.") from e
    return Kiwi()


_KEEP_TAGS = ("NN", "VV", "VA", "XR", "SL", "SN", "SH")


def kiwi_tokenize(text: str) -> list[str]:
    return [t.form for t in _kiwi().tokenize(text) if t.tag.startswith(_KEEP_TAGS)]


def get_tokenizer(name: str) -> Callable[[str], list[str]]:
    if name == "whitespace":
        return whitespace_tokenize
    if name == "kiwi":
        return kiwi_tokenize
    raise ValueError(f"알 수 없는 BM25_TOKENIZER: {name}")

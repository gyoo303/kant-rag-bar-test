"""BM25용 한국어 토큰화 (ADR-009, 스택 주의 S-07). Kiwi 내용 형태소만 남긴다."""

from __future__ import annotations

from typing import Any

# 명사·대명사·수사, 동사·형용사 어간, 어근, 외국어·숫자·한자
CONTENT_TAGS = frozenset({"NNG", "NNP", "NNB", "NR", "NP", "VV", "VA", "XR", "SL", "SN", "SH"})


class KiwiTokenizer:
    """`Tokenizer` 계약 구현. Kiwi 모델은 처음 호출할 때 한 번만 적재한다(S-07)."""

    def __init__(self) -> None:
        self._kiwi: Any = None

    def __call__(self, text: str) -> list[str]:
        if self._kiwi is None:
            from kiwipiepy import Kiwi

            self._kiwi = Kiwi()
        return [token.form for token in self._kiwi.tokenize(text) if token.tag in CONTENT_TAGS]

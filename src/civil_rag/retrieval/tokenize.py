"""BM25 토큰화.

- whitespace: 교안 5-1 방식 (lambda t: t.split()) — 기본값
- bigram    : 어절 + 한글 2글자 조각 (조사 붙은 단어도 매칭, 비교 실험용)
- kiwi      : 형태소 분석 (조사 분리, 복합명사 분해). 최규형 브랜치와 같은 선택. kiwipiepy 의존성 포함
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


_HANGUL = re.compile(r"[가-힣]{2,}")


def bigram_tokenize(text: str) -> list[str]:
    """어절 + 한글 2글자 조각. '계약을'·'계약' 처럼 조사가 붙어도 '계약' 조각이 겹쳐 매칭된다.
    (서상혁 브랜치의 simple 토크나이저와 같은 발상, 형태소 분석기 없이 동작)"""
    words = whitespace_tokenize(text)
    grams: list[str] = []
    for w in words:
        for m in _HANGUL.finditer(w):
            s = m.group(0)
            grams.extend(s[i:i + 2] for i in range(len(s) - 1))
    return words + grams


def tokenize_many(name: str, texts: list[str]) -> list[list[str]]:
    if name == "kiwi":  # Kiwi 는 여러 문장을 넘기면 내부 스레드로 병렬 처리
        kiwi = _kiwi()
        return [[t.form for t in toks if t.tag.startswith(_KEEP_TAGS)] for toks in kiwi.tokenize(texts)]
    fn = get_tokenizer(name)
    return [fn(t) for t in texts]


def cached_tokens(name: str, ids: list[str], texts: list[str]) -> list[list[str]]:
    """BM25 용 토큰화 결과를 색인 폴더에 캐시 (청크 ID·본문이 바뀌면 다시 만든다). whitespace 는 빨라서 캐시 안 함."""
    if name == "whitespace":
        return tokenize_many(name, texts)
    import hashlib
    import pickle

    from civil_rag import config

    h = hashlib.sha1()
    for i, t in zip(ids, texts):
        h.update(i.encode())
        h.update(b"|")
        h.update(t.encode())
        h.update(b"\x1e")
    path = config.INDEX_DIR / f"bm25_tokens_{name}.pkl"
    key = h.hexdigest()
    if path.exists():
        try:
            with path.open("rb") as f:
                saved = pickle.load(f)
            if saved.get("key") == key:
                return saved["tokens"]
        except Exception:  # noqa: BLE001 — 깨진 캐시는 다시 만든다
            pass
    tokens = tokenize_many(name, texts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump({"key": key, "tokens": tokens}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return tokens


def get_tokenizer(name: str) -> Callable[[str], list[str]]:
    if name == "whitespace":
        return whitespace_tokenize
    if name == "bigram":
        return bigram_tokenize
    if name == "kiwi":
        return kiwi_tokenize
    raise ValueError(f"알 수 없는 BM25_TOKENIZER: {name}")

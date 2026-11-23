"""모델 생성 (교안 기준: init_chat_model + OpenAIEmbeddings + CacheBackedEmbeddings)."""

from __future__ import annotations

from functools import lru_cache

from civil_rag import config


@lru_cache(maxsize=4)
def chat_model(model: str | None = None):
    """교안 방식(init_chat_model). 모델은 팀 통일 gpt-6-luna, temperature 는 config 값(기본 미지정)."""
    from langchain.chat_models import init_chat_model

    kwargs = {"timeout": config.LLM_TIMEOUT, "max_retries": 2}
    if config.LLM_TEMPERATURE is not None:
        kwargs["temperature"] = config.LLM_TEMPERATURE
    return init_chat_model(model=model or config.LLM_MODEL, model_provider="openai", **kwargs)


@lru_cache(maxsize=1)
def embeddings():
    """교안 2-4: OpenAIEmbeddings + 로컬 파일 캐시 (같은 청크 재색인 시 API 재호출 안 함)."""
    from langchain_classic.embeddings import CacheBackedEmbeddings
    from langchain_classic.storage import LocalFileStore
    from langchain_openai import OpenAIEmbeddings

    base = OpenAIEmbeddings(model=config.EMBEDDING_MODEL)
    store = LocalFileStore(str(config.CACHE_DIR / "embeddings"))
    return CacheBackedEmbeddings.from_bytes_store(
        base,
        store,
        namespace=config.EMBEDDING_MODEL,
        query_embedding_cache=True,
        key_encoder="sha256",
    )


@lru_cache(maxsize=1)
def cross_encoder():
    """교안 5-4: HuggingFaceCrossEncoder(Dongjin-kr/ko-reranker). 첫 호출 때 모델을 내려받는다."""
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

    return HuggingFaceCrossEncoder(model_name=config.RERANKER_MODEL)

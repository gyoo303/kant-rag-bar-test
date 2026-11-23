"""생성 모델 생성기 (LangChain init_chat_model). 공급자는 .env 의 LLM_PROVIDER/LLM_MODEL 로 선택."""

from __future__ import annotations

from functools import lru_cache


@lru_cache
def get_chat_model(provider: str, model: str, max_tokens: int):
    from langchain.chat_models import init_chat_model

    # temperature 등 샘플링 파라미터는 지정하지 않습니다 (최신 Claude 모델은 거부).
    return init_chat_model(model, model_provider=provider, max_tokens=max_tokens, max_retries=2)

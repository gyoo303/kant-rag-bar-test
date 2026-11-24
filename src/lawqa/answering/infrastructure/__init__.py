"""answering 외부 연결(생성 모델·프롬프트)과 조립 함수(CONV-03 `build_*`)."""

from __future__ import annotations

from lawqa.answering.infrastructure.generator import AnswerPrompt, OpenAIAnswerGenerator, chat_model
from lawqa.shared.settings import Settings


def build_generator(settings: Settings) -> OpenAIAnswerGenerator:
    """§5.1 생성기. 모델·시간 제한은 모든 구성이 같다(INV-08, `base` 설정을 넘긴다)."""
    chat = chat_model(
        settings.models.generation,
        settings.secrets.require("openai_api_key"),
        settings.timeouts.generation_s,
    )
    return OpenAIAnswerGenerator(chat, AnswerPrompt.load())

"""생성 모델 호출 (04-interfaces-api §5.1, ADR-013, S-06).

- 프롬프트는 `prompts/answer.txt`(코드 문자열 아님). 파일 내용 해시 = `prompt_sha`.
- 근거 문서는 `<doc id=… location=…>` 태그로 감싸고 본문의 `<`·`>`·`&`는 이스케이프한다
  (문서 안 문장이 태그를 닫고 지시처럼 보이지 않게, INV-09).
- `ChatOpenAI(...).with_structured_output(json_schema, method="json_schema", include_raw=True)`.
- 외부 오류 → `ModelTimeoutError`·`ModelCallError`, 파싱 실패 → `ModelOutputFormatError`.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from importlib import resources
from string import Template
from typing import Any

import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from lawqa.answering.domain.errors import ModelCallError, ModelOutputFormatError, ModelTimeoutError
from lawqa.answering.domain.models import ModelAnswer, Verdict
from lawqa.retrieval.domain.models import Candidate, ExamItem
from lawqa.shared.versioning import sha256_of

PROMPT_PACKAGE = "lawqa.answering.infrastructure"
PROMPT_FILE = "prompts/answer.txt"
MAX_TOKENS = 2000  # §5.1

# §5.1 출력 스키마(구조화 출력, strict)
ANSWER_SCHEMA: dict[str, Any] = {
    "title": "ModelAnswer",
    "description": "민법 선택형 문항 답변: 보기별 판단·근거 문서 id·정답 번호",
    "type": "object",
    "properties": {
        "answer": {
            "type": ["integer", "null"],
            "description": "정답 보기 번호 1~5, 근거 부족이면 null",
        },
        "sufficient": {"type": "boolean", "description": "정답 판단에 필요한 근거가 문서에 있는가"},
        "options": {
            "type": "array",
            "description": "보기 1~5 각각의 판단(정확히 5개)",
            "items": {
                "type": "object",
                "properties": {
                    "no": {"type": "integer"},
                    "verdict": {"type": "string", "enum": [v.value for v in Verdict]},
                    "reason": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["no", "verdict", "reason", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "sufficient", "options"],
    "additionalProperties": False,
}


class AnswerPrompt:
    """`answer.txt`의 `### SYSTEM`·`### USER` 절. USER는 `$question`·`$documents` 자리."""

    def __init__(self, text: str) -> None:
        if "### SYSTEM" not in text or "### USER" not in text:
            raise ValueError("answer.txt에 ### SYSTEM, ### USER 절이 있어야 합니다.")
        head, user = text.split("### USER", 1)
        self.system = head.split("### SYSTEM", 1)[1].strip()
        self.user = Template(user.strip())
        self.sha = sha256_of(text.encode("utf-8"))

    @classmethod
    def load(cls) -> AnswerPrompt:
        path = resources.files(PROMPT_PACKAGE).joinpath(PROMPT_FILE)
        return cls(path.read_text(encoding="utf-8"))

    def messages(self, item: ExamItem, context: Sequence[Candidate]) -> list[BaseMessage]:
        question = "\n".join(
            [f"지문: {item.stem.strip()}", "보기:"]
            + [f"{no}. {option.strip()}" for no, option in enumerate(item.options, start=1)]
        )
        documents = "\n".join(
            f'<doc id="{_attr(c.chunk_id)}" location="{_attr(c.location)}">'
            f"{html.escape(c.text, quote=False)}</doc>"
            for c in context
        )
        user = self.user.substitute(question=question, documents=documents or "(문서 없음)")
        return [SystemMessage(self.system), HumanMessage(user)]


class OpenAIAnswerGenerator:
    """`AnswerGenerator` 계약 구현(운영: OpenAI `ChatOpenAI`)."""

    def __init__(self, chat: BaseChatModel, prompt: AnswerPrompt) -> None:
        self._prompt = prompt
        self._chain = chat.with_structured_output(
            ANSWER_SCHEMA, method="json_schema", include_raw=True, strict=True
        )

    @property
    def prompt_sha(self) -> str:
        return self._prompt.sha

    def generate(self, item: ExamItem, context: Sequence[Candidate]) -> ModelAnswer:
        try:
            result = self._chain.invoke(self._prompt.messages(item, context))
        except openai.APITimeoutError as exc:
            raise ModelTimeoutError(f"생성 시간 초과: {exc}") from exc
        except openai.OpenAIError as exc:
            raise ModelCallError(f"생성 호출 실패: {type(exc).__name__}: {exc}") from exc
        raw = result.get("raw") if isinstance(result, dict) else None
        raw_output = _content(raw)
        parsed = result.get("parsed") if isinstance(result, dict) else None
        if not isinstance(parsed, dict):
            error = result.get("parsing_error") if isinstance(result, dict) else None
            raise ModelOutputFormatError(f"구조화 출력 파싱 실패: {error!r}", raw_output)
        try:
            return ModelAnswer.from_dict(parsed, raw_output=raw_output)
        except ModelOutputFormatError as exc:
            raise ModelOutputFormatError(str(exc), raw_output) from exc


def chat_model(model: str, api_key: str, timeout_s: float, max_retries: int = 2) -> BaseChatModel:
    """§5.1 생성 모델(`max_tokens=2000`, 시간 제한·재시도 2회).

    `temperature`는 넘기지 않는다: gpt-6-luna는 기본값(1) 외의 temperature를 거부한다
    (2026-11-24 실제 호출에서 400 "Only the default (1) value is supported"). §5.1의
    `temperature=0`과 다름 — 브리핑·ARCH 갱신 요청.
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        max_tokens=MAX_TOKENS,
        timeout=timeout_s,
        max_retries=max_retries,
    )


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _content(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)

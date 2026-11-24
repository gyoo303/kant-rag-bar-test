"""쿼리 리라이트 (D-005 필수 최적화, 04-interfaces-api §5.2, INV-10).

- 입력은 문항(지문·보기)뿐이다. 정답·기대 답·허용 근거는 들어갈 자리가 없다(INV-04, AC-10-3).
- 출력 `{"queries": [{"option_no", "query"}]}`. 보기 하나의 검색어가 없거나 비었거나 120자를
  넘으면 그 보기만 원 질의(`fallback=True`). 호출 실패·시간 초과·파싱 실패는
  `RewriteFailedError`(서비스가 모든 보기를 원 질의로).
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from importlib import resources
from string import Template
from typing import Any

import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from lawqa.retrieval.domain.errors import RewriteFailedError
from lawqa.retrieval.domain.models import ExamItem, OptionQuery
from lawqa.shared.versioning import sha256_of

PROMPT_PACKAGE = "lawqa.retrieval.infrastructure"
PROMPT_FILE = "prompts/rewrite.txt"
MAX_TOKENS = 800  # §5.2
QUERY_MAX_CHARS = 120

REWRITE_SCHEMA: dict[str, Any] = {
    "title": "RewrittenQueries",
    "description": "보기별 법률 용어 검색어",
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "option_no": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": ["option_no", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}


class RewritePrompt:
    def __init__(self, text: str) -> None:
        if "### SYSTEM" not in text or "### USER" not in text:
            raise ValueError("rewrite.txt에 ### SYSTEM, ### USER 절이 있어야 합니다.")
        head, user = text.split("### USER", 1)
        self.system = head.split("### SYSTEM", 1)[1].strip()
        self.user = Template(user.strip())
        self.sha = sha256_of(text.encode("utf-8"))

    @classmethod
    def load(cls) -> RewritePrompt:
        path = resources.files(PROMPT_PACKAGE).joinpath(PROMPT_FILE)
        return cls(path.read_text(encoding="utf-8"))

    def messages(self, item: ExamItem) -> list[BaseMessage]:
        """모델 입력. 문항의 지문·보기만 쓴다(AC-10-3)."""
        question = "\n".join(
            [f"지문: {html.escape(item.stem.strip(), quote=False)}", "보기:"]
            + [
                f"{no}. {html.escape(option.strip(), quote=False)}"
                for no, option in enumerate(item.options, start=1)
            ]
        )
        return [SystemMessage(self.system), HumanMessage(self.user.substitute(question=question))]


class OpenAIQueryRewriter:
    """`QueryRewriterPort` 구현."""

    def __init__(self, chat: BaseChatModel, prompt: RewritePrompt) -> None:
        self._prompt = prompt
        self._chain = chat.with_structured_output(
            REWRITE_SCHEMA, method="json_schema", include_raw=False, strict=True
        )

    @property
    def prompt_sha(self) -> str:
        return self._prompt.sha

    def rewrite(self, item: ExamItem, queries: list[OptionQuery]) -> list[OptionQuery]:
        try:
            parsed = self._chain.invoke(self._prompt.messages(item))
        except openai.OpenAIError as exc:
            raise RewriteFailedError(f"리라이트 호출 실패: {type(exc).__name__}") from exc
        except (ValueError, TypeError) as exc:  # 구조화 출력 파싱 실패
            raise RewriteFailedError(f"리라이트 출력 형식 오류: {exc}") from exc
        return merge_rewrites(queries, _query_map(parsed))


def merge_rewrites(queries: Sequence[OptionQuery], rewritten: dict[int, str]) -> list[OptionQuery]:
    """보기마다 쓸 만한 검색어가 있으면 `rewritten`, 없으면 원 질의 + `fallback=True`."""
    merged = []
    for q in queries:
        text = rewritten.get(q.option_no, "").strip()
        if text and len(text) <= QUERY_MAX_CHARS:
            merged.append(OptionQuery(q.option_no, q.original, text))
        else:
            merged.append(OptionQuery(q.option_no, q.original, None, fallback=True))
    return merged


def _query_map(parsed: Any) -> dict[int, str]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("queries"), list):
        raise RewriteFailedError("리라이트 출력에 queries 목록이 없습니다.")
    result: dict[int, str] = {}
    for entry in parsed["queries"]:
        if not isinstance(entry, dict):
            continue
        no, query = entry.get("option_no"), entry.get("query")
        if isinstance(no, int) and not isinstance(no, bool) and isinstance(query, str):
            result.setdefault(no, query)  # 같은 보기가 두 번 오면 처음 것
    return result


def chat_model(model: str, api_key: str, timeout_s: float) -> BaseChatModel:
    """§5.2 리라이트 모델(`max_tokens=800`, 재시도 1회). temperature는 생성기와 같은 이유로 생략."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, api_key=api_key, max_tokens=MAX_TOKENS, timeout=timeout_s, max_retries=1
    )

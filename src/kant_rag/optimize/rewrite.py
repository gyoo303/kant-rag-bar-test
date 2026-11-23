"""쿼리 리라이트: 원질문 → 검색용 질의. 실패하면 원질문으로 fallback.

주의: 정답·허용 근거를 리라이터 입력에 넣지 않습니다 (질문만 입력).
"""

from __future__ import annotations

from kant_rag.config import Settings
from kant_rag.generation.llm import get_chat_model
from kant_rag.generation.prompts import REWRITE_SYSTEM


def rewrite_query(question: str, settings: Settings) -> tuple[str, dict]:
    info: dict = {"original": question, "rewritten": None, "fallback": False, "error": None}
    try:
        llm = get_chat_model(settings.models.llm_provider, settings.models.llm_model, 256)
        msg = llm.invoke([("system", REWRITE_SYSTEM), ("human", question)])
        text = msg.content if isinstance(msg.content, str) else "".join(
            b.get("text", "") for b in msg.content if isinstance(b, dict))
        text = text.strip().splitlines()[0].strip() if text.strip() else ""
        if not text or len(text) > 4 * max(len(question), 50):
            raise ValueError("비어 있거나 비정상적으로 긴 리라이트")
        info["rewritten"] = text
        return text, info
    except Exception as e:
        info.update(fallback=True, error=f"{type(e).__name__}: {e}", rewritten=question)
        return question, info

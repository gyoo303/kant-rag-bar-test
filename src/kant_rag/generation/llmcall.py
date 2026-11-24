"""LLM 호출 공통 처리: 응답 텍스트·종료 사유·토큰 사용량 기록, 빈 응답/한도 초과 시 1회 재시도, 견고한 JSON 추출.

추론형 모델(gpt-6-luna 등)은 추론에 쓴 토큰도 출력 한도에 포함되므로, 한도가 작으면
본문 없이 끝날 수 있다(finish_reason=length). 이때 한도를 2배로 늘려 한 번 더 호출하고 기록을 남긴다.
"""

from __future__ import annotations

import json
import re

from kant_rag.generation.llm import get_chat_model

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def text_of(msg) -> str:
    c = msg.content
    return c if isinstance(c, str) else "".join(
        b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def _meta(msg, max_tokens: int) -> dict:
    rm = getattr(msg, "response_metadata", {}) or {}
    um = getattr(msg, "usage_metadata", None) or {}
    out = {
        "max_tokens": max_tokens,
        "finish_reason": rm.get("finish_reason") or rm.get("stop_reason"),
        "model": rm.get("model_name") or rm.get("model"),
        "input_tokens": um.get("input_tokens"),
        "output_tokens": um.get("output_tokens"),
    }
    details = um.get("output_token_details") or {}
    if details.get("reasoning") is not None:
        out["reasoning_tokens"] = details.get("reasoning")
    return out


def call_llm(provider: str, model: str, messages: list, max_tokens: int, retry_factor: int = 2) -> tuple[str, list[dict]]:
    """반환: (응답 텍스트, 호출별 메타 목록). 빈 응답이거나 한도로 끊기면 한도를 늘려 1회 재시도."""
    calls: list[dict] = []
    budget = max_tokens
    for attempt in range(2):
        msg = get_chat_model(provider, model, budget).invoke(messages)
        text = text_of(msg)
        meta = _meta(msg, budget)
        meta["attempt"] = attempt + 1
        meta["empty"] = not text.strip()
        calls.append(meta)
        if text.strip() and meta.get("finish_reason") not in ("length", "max_tokens"):
            return text, calls
        budget *= retry_factor
    return text, calls


def extract_json(text: str, required_key: str | None = None) -> dict:
    """응답에서 첫 번째 완결 JSON 객체를 꺼냄 (앞뒤 설명·코드펜스·중괄호가 섞여도 됨)."""
    if not text or not text.strip():
        raise ValueError("빈 응답 (출력 한도 초과 가능성)")
    t = FENCE.sub("", text.strip())
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and (required_key is None or required_key in obj):
            return obj
    raise ValueError("JSON 객체를 찾지 못함")

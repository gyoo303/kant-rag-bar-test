"""근거 기반 답변: 검색 결과 → 컨텍스트 → LLM → 인용 검증."""

from __future__ import annotations

import json
import re

from kant_rag.config import Settings
from kant_rag.generation.llm import get_chat_model
from kant_rag.generation.prompts import ANSWER_SYSTEM, ANSWER_USER
from kant_rag.schemas import AnswerResult, AnswerStatus, Citation, LLMAnswer, RetrievedChunk

INSUFFICIENT_MSG = "제공된 문서에서 이 질문에 답할 근거를 찾지 못했습니다. 담당 부서에 확인해 주세요."


def build_context(chunks: list[RetrievedChunk], max_chunks: int, max_chars: int) -> tuple[str, list[RetrievedChunk]]:
    used, parts, total = [], [], 0
    for r in chunks[:max_chunks]:
        block = f'<chunk id="{r.chunk.chunk_id}" doc="{r.chunk.title}" loc="{r.chunk.location()}">\n{r.chunk.text}\n</chunk>'
        if total + len(block) > max_chars and used:
            break
        parts.append(block)
        used.append(r)
        total += len(block)
    return "\n\n".join(parts), used


def _parse(text: str) -> LLMAnswer:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("JSON 응답을 찾지 못했습니다")
    return LLMAnswer.model_validate(json.loads(m.group(0)))


def _text_of(msg) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def generate_answer(
    question: str,
    retrieved: list[RetrievedChunk],
    settings: Settings,
    min_rerank_score: float | None = None,
) -> tuple[AnswerResult, dict]:
    """반환: (답변 결과, 기록용 부가정보)."""
    g = settings.generation
    info: dict = {"context_chunk_ids": [], "gate": None, "raw_output": None}

    if not retrieved:
        info["gate"] = "no_candidates"
        return AnswerResult(question=question, answer=INSUFFICIENT_MSG, status=AnswerStatus.INSUFFICIENT), info

    # C 구성에서만: reranker 최고 점수가 임계값 미만이면 생성 없이 근거 부족 안내
    if min_rerank_score is not None and retrieved[0].source == "rerank" and retrieved[0].score < min_rerank_score:
        info["gate"] = f"rerank_top<{min_rerank_score}"
        return AnswerResult(question=question, answer=INSUFFICIENT_MSG, status=AnswerStatus.INSUFFICIENT), info

    context, used = build_context(retrieved, g.max_context_chunks, g.max_context_chars)
    info["context_chunk_ids"] = [u.chunk.chunk_id for u in used]

    try:
        llm = get_chat_model(settings.models.llm_provider, settings.models.llm_model, g.max_tokens)
        msg = llm.invoke([("system", ANSWER_SYSTEM), ("human", ANSWER_USER.format(context=context, question=question))])
        raw = _text_of(msg)
        info["raw_output"] = raw
        parsed = _parse(raw)
    except Exception as e:  # 모델 오류는 '근거 없음'과 구분해 기록
        return AnswerResult(question=question, answer="", status=AnswerStatus.GENERATION_ERROR,
                            error=f"{type(e).__name__}: {e}"), info

    by_id = {u.chunk.chunk_id: u.chunk for u in used}
    invalid = [c for c in parsed.cited_chunk_ids if c not in by_id]
    citations = [
        Citation(chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, location=c.location(), quote=c.text[:300])
        for cid in dict.fromkeys(parsed.cited_chunk_ids) if (c := by_id.get(cid))
    ]

    if not parsed.answerable:
        status = AnswerStatus.INSUFFICIENT
    elif invalid or not citations:
        status = AnswerStatus.INVALID_CITATION
    else:
        status = AnswerStatus.OK
    err = f"검색되지 않은 인용: {invalid}" if invalid else None
    return AnswerResult(question=question, answer=parsed.answer, status=status,
                        citations=citations, error=err), info

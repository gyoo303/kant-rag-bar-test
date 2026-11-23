"""선택형 풀이: 진술별 검색 → LLM 진술 정오 판단 → 규칙으로 정답 번호 결정.

LLM 에게 번호를 직접 고르게 하지 않고, 진술별 판단(verdict)과 발문의 극성/형식(옳은 것/옳지 않은 것,
단일/조합/개수)으로 정답을 계산합니다. 덕분에 '검색 누락 → 진술 판단 오류 → 정답 오류' 를 단계별로 분석할 수 있습니다.
"""

from __future__ import annotations

import json
import re
import time

from kant_rag.config import Settings
from kant_rag.generation.llm import get_chat_model
from kant_rag.mcq.parse import parse_combo, parse_ox
from kant_rag.mcq.prompts import MCQ_SYSTEM, MCQ_USER
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.retrieval.pipeline import RetrievalMode, Retriever
from kant_rag.schemas import RetrievedChunk


def statement_query(q: ExamQuestion, statement: str, stem_chars: int) -> str:
    stem = q.stem[:stem_chars]
    return f"{stem}\n{statement}" if stem else statement


def _support(j: StatementJudgment | None, want: bool) -> float:
    """진술이 want(true/false) 일 정도. unknown/누락은 0.5."""
    if j is None or j.verdict == "unknown":
        return 0.5
    p = 0.5 + 0.5 * j.confidence
    return p if (j.verdict == "true") == want else 1 - p


def choose_answer(q: ExamQuestion, judgments: dict[str, StatementJudgment]) -> tuple[int | None, dict[int, float]]:
    """진술 판단 → 보기별 점수 → 최고점 보기. 모든 판단이 unknown 이면 None (근거 부족)."""
    if not judgments or all(j.verdict == "unknown" for j in judgments.values()):
        return None, {}
    target = q.polarity == "correct"  # '옳은 것' 을 찾는가
    scores: dict[int, float] = {}
    if q.form == "single":
        for n in q.options:
            scores[n] = _support(judgments.get(str(n)), target)
    elif q.form == "combination":
        for n, text in q.options.items():
            chosen = parse_combo(text)
            # 고른 진술은 target, 고르지 않은 진술은 반대여야 함 → 로그 우도 대신 곱의 평균
            s = 1.0
            for key in q.items:
                s *= _support(judgments.get(key), target if key in chosen else not target)
            scores[n] = s
    elif q.form == "ox":
        for n, text in q.options.items():
            labels = parse_ox(text)
            s = 1.0
            for key in q.items:
                s *= _support(judgments.get(key), labels[key]) if key in labels else 0.5
            scores[n] = s
    else:  # count
        expected = sum(_support(judgments.get(k), target) for k in q.items)
        for n, text in q.options.items():
            m = re.search(r"(\d+)", text)
            scores[n] = -abs(int(m.group(1)) - expected) if m else float("-inf")
    best = max(scores, key=lambda n: (scores[n], -n))
    return best, scores


def _parse_judgments(raw: str, keys: list[str]) -> dict[str, StatementJudgment]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("JSON 응답 없음")
    data = json.loads(m.group(0)).get("judgments", {})
    return {k: StatementJudgment.model_validate(data[k]) for k in keys if k in data}


def _evidence_block(per_statement: dict[str, list[RetrievedChunk]], k: int, max_chars: int) -> tuple[str, list[str]]:
    seen: dict[str, RetrievedChunk] = {}
    for key, results in per_statement.items():  # 진술 순서대로, 진술당 상위 k 개, 중복 제거
        for r in results[:k]:
            seen.setdefault(r.chunk.chunk_id, r)
    parts, used, total = [], [], 0
    for cid, r in seen.items():
        block = f'<doc id="{cid}" title="{r.chunk.title}" loc="{r.chunk.location()}">\n{r.chunk.text}\n</doc>'
        if total + len(block) > max_chars and used:
            break
        parts.append(block)
        used.append(cid)
        total += len(block)
    return "\n\n".join(parts), used


class MCQSolver:
    def __init__(self, settings: Settings, retriever: Retriever | None = None):
        self.s = settings
        self.retriever = retriever or Retriever(settings)

    def solve(self, q: ExamQuestion, mode: RetrievalMode = RetrievalMode.C, run_id: str | None = None) -> dict:
        """정답(q.answer)은 입력에 쓰지 않습니다. 반환값은 실행 기록(record)."""
        c = self.s.mcq
        t0 = time.perf_counter()
        statements = q.statements()
        rec: dict = {
            "run_id": run_id, "question_id": q.id, "number": q.number, "config": mode.value,
            "form": q.form, "polarity": q.polarity, "versions": self.s.versions.model_dump(),
            "models": self.s.models.model_dump(), "settings_fingerprint": self.s.fingerprint(),
            "timing_ms": {}, "status": "ok", "error": None,
        }

        t = time.perf_counter()
        per_statement: dict[str, list[RetrievedChunk]] = {}
        rec["retrieval"] = {}
        try:
            for key, text in statements.items():
                stages = self.retriever.retrieve(statement_query(q, text, c.stem_chars_in_query), mode)
                per_statement[key] = stages["final"]
                rec["retrieval"][key] = [
                    {"rank": r.rank, "chunk_id": r.chunk.chunk_id, "score": r.score, **r.trace}
                    for r in stages["final"]
                ]
        except Exception as e:
            rec.update(status="retrieval_error", error=f"{type(e).__name__}: {e}", predicted=None)
            rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        rec["timing_ms"]["retrieval"] = round((time.perf_counter() - t) * 1000, 1)

        evidence, used = _evidence_block(per_statement, c.per_statement_k, c.max_context_chars)
        rec["context_chunk_ids"] = used
        listing = "\n".join(f"{k}. {v}" for k, v in statements.items())

        t = time.perf_counter()
        try:
            llm = get_chat_model(self.s.models.llm_provider, self.s.models.llm_model, c.max_tokens)
            msg = llm.invoke([("system", MCQ_SYSTEM), ("human", MCQ_USER.format(
                evidence=evidence, stem=q.stem, statements=listing, keys=", ".join(statements)))])
            raw = msg.content if isinstance(msg.content, str) else "".join(
                b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text")
            rec["raw_output"] = raw
            judgments = _parse_judgments(raw, list(statements))
        except Exception as e:
            rec.update(status="generation_error", error=f"{type(e).__name__}: {e}", predicted=None)
            rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        rec["timing_ms"]["generation"] = round((time.perf_counter() - t) * 1000, 1)

        invalid = sorted({cid for j in judgments.values() for cid in j.cited_chunk_ids if cid not in used})
        predicted, scores = choose_answer(q, judgments)
        rec.update(
            judgments={k: j.model_dump() for k, j in judgments.items()},
            missing_judgments=[k for k in statements if k not in judgments],
            invalid_citations=invalid,
            option_scores=scores,
            predicted=predicted,
        )
        if predicted is None:
            rec["status"] = "insufficient_evidence"
        elif invalid:
            rec["status"] = "invalid_citation"
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec

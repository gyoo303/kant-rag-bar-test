"""선택형 풀이: 진술별 검색 → LLM 진술 정오 판단 → 규칙으로 정답 번호 결정.

LLM 에게 번호를 직접 고르게 하지 않고, 진술별 판단(verdict)과 발문의 극성/형식(옳은 것/옳지 않은 것,
단일/조합/개수)으로 정답을 계산합니다. 덕분에 '검색 누락 → 진술 판단 오류 → 정답 오류' 를 단계별로 분석할 수 있습니다.
"""

from __future__ import annotations

import re
import time

from kant_rag.config import Settings
from kant_rag.generation.llmcall import call_llm, extract_json
from kant_rag.mcq.parse import parse_combo, parse_ox
from kant_rag.mcq.prompts import (
    MCQ_CLOSED_SYSTEM,
    MCQ_CLOSED_USER,
    MCQ_REWRITE_SYSTEM,
    MCQ_REWRITE_USER,
    MCQ_SYSTEM,
    MCQ_USER,
)
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


def _text(msg) -> str:
    c = msg.content
    return c if isinstance(c, str) else "".join(
        b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def rewrite_statement_queries(q: ExamQuestion, settings: Settings) -> tuple[dict[str, str], dict]:
    """진술별 검색 질의 생성 (문항당 LLM 1회). 정답·근거는 입력하지 않음. 실패/이상 키는 원래 질의로 fallback."""
    c = settings.mcq
    statements = q.statements()
    original = {k: statement_query(q, v, c.stem_chars_in_query) for k, v in statements.items()}
    info: dict = {"original": original, "rewritten": {}, "fallback_keys": [], "error": None}
    try:
        listing = "\n".join(f"{k}. {v}" for k, v in statements.items())
        raw, calls = call_llm(settings.models.llm_provider, settings.models.llm_model,
                              [("system", MCQ_REWRITE_SYSTEM), ("human", MCQ_REWRITE_USER.format(
                                  stem=q.stem[: c.stem_chars_in_query], statements=listing))], c.rewrite_max_tokens)
        info["llm_calls"] = calls
        data = extract_json(raw)
    except Exception as e:
        data = {}
        info["error"] = f"{type(e).__name__}: {e}"
    queries = {}
    for k in statements:
        v = data.get(k)
        if isinstance(v, str) and 2 <= len(v.strip()) <= 300:
            queries[k] = v.strip()
        else:
            queries[k] = original[k]
            info["fallback_keys"].append(k)
    info["rewritten"] = queries
    return queries, info


def _parse_judgments(raw: str, keys: list[str]) -> dict[str, StatementJudgment]:
    data = extract_json(raw, "judgments").get("judgments", {})
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
        self._retriever = retriever

    @property
    def retriever(self) -> Retriever:  # closed-book 만 돌릴 때는 색인을 읽지 않음
        if self._retriever is None:
            self._retriever = Retriever(self.s)
        return self._retriever

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

        listing = "\n".join(f"{k}. {v}" for k, v in statements.items())
        if mode == RetrievalMode.NONE:
            return self._judge(q, rec, t0, MCQ_CLOSED_SYSTEM,
                               MCQ_CLOSED_USER.format(stem=q.stem, statements=listing, keys=", ".join(statements)),
                               used=[])

        if self.s.optimization.rewrite.enabled:
            t = time.perf_counter()
            queries, rec["rewrite"] = rewrite_statement_queries(q, self.s)
            rec["timing_ms"]["rewrite"] = round((time.perf_counter() - t) * 1000, 1)
        else:
            queries = {k: statement_query(q, v, c.stem_chars_in_query) for k, v in statements.items()}
        rec["search_queries"] = queries

        t = time.perf_counter()
        per_statement: dict[str, list[RetrievedChunk]] = {}
        rec["retrieval"] = {}
        try:
            for key in statements:
                stages = self.retriever.retrieve(queries[key], mode)
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
        return self._judge(q, rec, t0, MCQ_SYSTEM, MCQ_USER.format(
            evidence=evidence, stem=q.stem, statements=listing, keys=", ".join(statements)), used)

    def _judge(self, q: ExamQuestion, rec: dict, t0: float, system: str, user: str, used: list[str]) -> dict:
        statements = q.statements()
        t = time.perf_counter()
        try:
            raw, calls = call_llm(self.s.models.llm_provider, self.s.models.llm_model,
                                  [("system", system), ("human", user)], self.s.mcq.max_tokens)
            rec.setdefault("llm_calls", []).extend({"step": "judge", **c} for c in calls)
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

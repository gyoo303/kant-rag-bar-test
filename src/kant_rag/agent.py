"""Knowledge Agent: (리라이트) → 검색(A/B/C) → 답변 → 실행 기록."""

from __future__ import annotations

import time
import traceback
import uuid

from kant_rag.config import Settings
from kant_rag.generation.answer import generate_answer
from kant_rag.optimize.cache import AnswerCache, cache_key
from kant_rag.optimize.rewrite import rewrite_query
from kant_rag.retrieval.pipeline import RetrievalMode, Retriever
from kant_rag.schemas import AnswerResult, AnswerStatus, RetrievedChunk


def _brief(results: list[RetrievedChunk]) -> list[dict]:
    return [{"rank": r.rank, "chunk_id": r.chunk.chunk_id, "score": r.score, **r.trace} for r in results]


class KnowledgeAgent:
    def __init__(self, settings: Settings, retriever: Retriever | None = None):
        self.s = settings
        self.retriever = retriever or Retriever(settings)
        opt = settings.optimization
        self.cache = (AnswerCache(settings.resolve(settings.paths.cache_db), opt.cache.ttl_seconds)
                      if opt.cache.enabled else None)

    def ask(self, question: str, mode: RetrievalMode = RetrievalMode.C, user_scope: str = "public",
            question_id: str | None = None, run_id: str | None = None) -> dict:
        """하나의 질문을 처리하고 평가 기록 규격(record)을 반환합니다."""
        t0 = time.perf_counter()
        record: dict = {
            "run_id": run_id or uuid.uuid4().hex[:8],
            "question_id": question_id,
            "config": mode.value,
            "question": question,
            "versions": self.s.versions.model_dump(),
            "models": self.s.models.model_dump(),
            "settings_fingerprint": self.s.fingerprint(),
            "optimization": {"cache": self.cache is not None, "rewrite": self.s.optimization.rewrite.enabled},
            "timing_ms": {},
        }

        key = None
        if self.cache:
            key = cache_key(question, self.s, mode.value, user_scope)
            hit = self.cache.get(key)
            record["cache"] = {"key": key[:16], "hit": hit is not None}
            if hit:
                record.update({k: hit[k] for k in ("answer", "retrieval")})
                record["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
                return record

        query = question
        if self.s.optimization.rewrite.enabled:
            t = time.perf_counter()
            query, rw = rewrite_query(question, self.s)
            record["rewrite"] = rw
            record["timing_ms"]["rewrite"] = round((time.perf_counter() - t) * 1000, 1)
        record["search_query"] = query

        t = time.perf_counter()
        try:
            stages = self.retriever.retrieve(query, mode)
        except Exception as e:
            record["answer"] = AnswerResult(question=question, answer="", status=AnswerStatus.RETRIEVAL_ERROR,
                                            error=f"{type(e).__name__}: {e}").model_dump(mode="json")
            record["retrieval"] = {}
            record["traceback"] = traceback.format_exc(limit=3)
            record["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return record
        record["timing_ms"]["retrieval"] = round((time.perf_counter() - t) * 1000, 1)
        record["retrieval"] = {name: _brief(v) for name, v in stages.items()}

        t = time.perf_counter()
        min_score = self.s.rerank.min_score if mode == RetrievalMode.C else None
        answer, info = generate_answer(question, stages["final"], self.s, min_rerank_score=min_score)
        record["timing_ms"]["generation"] = round((time.perf_counter() - t) * 1000, 1)
        record["answer"] = answer.model_dump(mode="json")
        record["generation"] = info
        record["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)

        if self.cache and key and answer.status == AnswerStatus.OK:  # 정상 답변만 캐시
            self.cache.set(key, {"answer": record["answer"], "retrieval": record["retrieval"]})
        return record

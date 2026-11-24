"""질문 → 검색 → (재정렬) → 근거 선택 → 답변·출처 / 근거 부족 안내 (노션 STEP 4)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from civil_rag.generation.answer import AnswerResult, generate, no_evidence_result
from civil_rag.retrieval.pipeline import Retriever
from civil_rag.retrieval.types import RetrievalResult

# 평가·화면에서 고르는 구성 이름
RUN_CONFIGS = {
    "LLM": {"mode": None, "rewrite": False},   # 기준선: 검색 없이 LLM 단독
    "A": {"mode": "A", "rewrite": False},
    "B": {"mode": "B", "rewrite": False},
    "C": {"mode": "C", "rewrite": False},
    "C+RW": {"mode": "C", "rewrite": True},     # 선택 최적화: 쿼리 리라이트
}


@dataclass
class AgentResult:
    question: str
    run_config: str
    retrieval: RetrievalResult | None
    answer: AnswerResult
    total_seconds: float

    @property
    def status(self) -> str:
        return self.answer.status

    def to_record(self) -> dict:
        return {
            "question": self.question,
            "run_config": self.run_config,
            "retrieval": self.retrieval.to_record() if self.retrieval else None,
            "answer": self.answer.to_record(),
            "total_seconds": self.total_seconds,
        }


class LegalRAG:
    def __init__(self, retriever: Retriever | None = None):
        self._retriever = retriever

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    def ask(self, question: str, run_config: str = "C", article: str | None = None) -> AgentResult:
        if run_config not in RUN_CONFIGS:
            raise ValueError(f"run_config 는 {list(RUN_CONFIGS)} 중 하나")
        spec = RUN_CONFIGS[run_config]
        t0 = time.perf_counter()
        if spec["mode"] is None:
            ans = generate(question, None, llm_only=True)
            return AgentResult(question, run_config, None, ans, time.perf_counter() - t0)

        try:
            ret = self.retriever.retrieve(question, mode=spec["mode"], rewrite=spec["rewrite"], article=article)
        except Exception as e:  # noqa: BLE001 — 검색 실패는 '근거 없음'이 아니라 error
            ans = AnswerResult(status="error", verdict=None, answer="", error=f"retrieval: {type(e).__name__}: {e}"[:500])
            return AgentResult(question, run_config, None, ans, time.perf_counter() - t0)

        ans = no_evidence_result() if ret.gated_out else generate(question, ret.final)
        return AgentResult(question, run_config, ret, ans, time.perf_counter() - t0)

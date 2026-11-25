"""답변 서비스 (04-interfaces-api §2·SEQ-03, ADR-004). 저장 없음.

**모든 예외를 `Answer`로 바꾸는 유일한 위치**다: 입력 오류·검색 실패·모델 오류는 각자의 결과
종류로, 예상 못 한 예외는 로그(`log.exception`)를 남기고 `MODEL_ERROR/UNEXPECTED`로 바꾼다.
화면·기록의 문구는 §4 문구만 쓰고 예외 원문은 로그에만 남긴다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from lawqa.answering.domain.errors import ModelCallError, ModelOutputFormatError, ModelTimeoutError
from lawqa.answering.domain.models import Answer, ErrorCode, Outcome, Verdict
from lawqa.answering.domain.ports import AnswerGenerator
from lawqa.retrieval.application.retrieval_service import RetrievalService
from lawqa.retrieval.domain.decomposer import followup_queries
from lawqa.retrieval.domain.errors import (
    IndexNotReadyError,
    InvalidExamItemError,
    RerankerFailedError,
    RetrievalFailedError,
)
from lawqa.retrieval.domain.models import (
    Candidate,
    ExamItem,
    OptionQuery,
    RetrievalConfig,
    RetrievalResult,
)
from lawqa.shared.logging_setup import log_event

log = logging.getLogger(__name__)

RETRIEVAL_MESSAGE = "검색 오류"
MODEL_MESSAGE = "답변 생성 오류"


@dataclass(frozen=True, slots=True)
class AnswerEnvelope:
    """답변 한 번의 결과와 기록용 정보(§2, AC-09-8)."""

    answer: Answer
    config_name: str
    retrieval: RetrievalResult | None
    context: tuple[Candidate, ...]
    prompt_sha: str
    raw_output: str
    latency_ms: int
    queries: tuple[OptionQuery, ...] = field(default=())
    retrieval_ms: int | None = None  # 리라이트·검색·재정렬 포함
    generation_ms: int | None = None
    followup_queries: tuple[str, ...] = ()  # CR-019: 2차 검색에 쓴 질의(없으면 비어 있음)
    followup_added: int = 0  # 2차 검색으로 컨텍스트에 더해진 청크 수

    @property
    def context_chars(self) -> int:
        return sum(len(c.text) for c in self.context)

    def to_dict(self) -> dict[str, Any]:
        """JSON으로 내보낼 형태(`ask` 출력, 실행 기록)."""
        a = self.answer
        return {
            "config": self.config_name,
            "outcome": a.outcome.value,
            "answer_no": a.answer_no,
            "evidence_sufficient": a.evidence_sufficient,  # CR-014: 두 번째 지표의 근거
            "error_code": a.error_code.value if a.error_code else None,
            "user_message": a.user_message,
            "judgments": [
                {
                    "option_no": j.option_no,
                    "verdict": j.verdict.value,
                    "reason": j.reason,
                    "citations": [
                        {"chunk_id": c.chunk_id, "location": c.location} for c in j.citations
                    ],
                }
                for j in a.judgments
            ],
            "dropped_citations": a.dropped_citations,
            "queries": [
                {
                    "option_no": q.option_no,
                    "original": q.original,
                    "rewritten": q.rewritten,
                    "fallback": q.fallback,
                }
                for q in self.queries
            ],
            "retrieval": None if self.retrieval is None else _retrieval_dict(self.retrieval),
            "context": [
                {"chunk_id": c.chunk_id, "location": c.location, "chars": len(c.text)}
                for c in self.context
            ],
            "context_count": len(self.context),
            "context_chars": self.context_chars,
            "prompt_sha": self.prompt_sha,
            "raw_output": self.raw_output,
            "latency_ms": self.latency_ms,
            "retrieval_ms": self.retrieval_ms,
            "generation_ms": self.generation_ms,
            "followup_queries": list(self.followup_queries),
            "followup_added": self.followup_added,
        }


class AnswerService:
    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        generator: AnswerGenerator,
        configs: Mapping[str, RetrievalConfig],
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._retrieval = retrieval
        self._generator = generator
        self._configs = configs
        self._timer = timer

    def answer(self, item_input: Mapping[str, Any], config_name: str) -> AnswerEnvelope:
        started = self._timer()
        config = self._configs.get(config_name)
        if config is None:
            raise ValueError(f"알 수 없는 구성: {config_name}")  # 호출 쪽 프로그램 오류
        result: RetrievalResult | None = None
        context: tuple[Candidate, ...] = ()
        raw_output = ""
        followups: tuple[str, ...] = ()
        added = 0
        retrieval_ms: int | None = None
        generation_ms: int | None = None
        try:
            item = _exam_item(item_input)
            stage = self._timer()
            result = self._retrieval.retrieve(item, config)  # C+R 리라이트·fallback 포함
            retrieval_ms = self._elapsed_ms(stage)
            context = tuple(result.context(config.k_opt))
            stage = self._timer()
            model_answer = self._generator.generate(item, context)
            generation_ms = self._elapsed_ms(stage)
            raw_output = model_answer.raw_output
            answer = Answer.from_model_output(
                model_answer,
                {c.chunk_id for c in context},
                {c.chunk_id: c.location for c in context},
            )
            if not answer.evidence_sufficient:
                retry = self._second_pass(item, config, answer, context)
                if retry is not None:
                    answer, context, raw_output, followups, added = retry
        except InvalidExamItemError as exc:
            answer = Answer.error(
                Outcome.INPUT_ERROR, ErrorCode.INVALID_INPUT, f"입력 오류: {exc.reason}"
            )
        except RetrievalFailedError as exc:
            answer = self._failed(Outcome.RETRIEVAL_ERROR, _retrieval_code(exc), exc)
        except ModelTimeoutError as exc:
            answer = self._failed(Outcome.MODEL_ERROR, ErrorCode.MODEL_TIMEOUT, exc)
        except ModelCallError as exc:
            answer = self._failed(Outcome.MODEL_ERROR, ErrorCode.MODEL_CALL_FAILED, exc)
        except ModelOutputFormatError as exc:
            raw_output = exc.raw_output or raw_output
            answer = self._failed(Outcome.MODEL_ERROR, ErrorCode.MODEL_OUTPUT_INVALID, exc)
        except Exception:  # ADR-004 유일한 최종 변환: 로그 후 결과로
            log.exception("answer_crash config=%s", config_name)
            answer = Answer.error(Outcome.MODEL_ERROR, ErrorCode.UNEXPECTED, MODEL_MESSAGE)
        latency_ms = self._elapsed_ms(started)
        log_event(
            log,
            "answer",
            config=config_name,
            outcome=answer.outcome.value,
            error_code=answer.error_code.value if answer.error_code else None,
            latency_ms=latency_ms,
        )
        return AnswerEnvelope(
            answer=answer,
            config_name=config_name,
            retrieval=result,
            context=context,
            prompt_sha=self._generator.prompt_sha,
            raw_output=raw_output,
            latency_ms=latency_ms,
            queries=tuple(o.query for o in result.options) if result else (),
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            followup_queries=followups,
            followup_added=added,
        )

    def _second_pass(
        self,
        item: ExamItem,
        config: RetrievalConfig,
        first: Answer,
        context: tuple[Candidate, ...],
    ) -> tuple[Answer, tuple[Candidate, ...], str, tuple[str, ...], int] | None:
        """근거가 모자란 보기의 명제만 다시 찾아 한 번 더 답한다 (CR-019).

        모델이 `insufficient`로 표시한 보기가 가리키는 명제로 2차 검색을 하고, 1차 컨텍스트에
        더해 다시 생성한다. **2차가 근거 충족일 때만 채택한다** — 아니면 1차를 그대로 둔다
        (근거 없이 답만 바뀌는 것을 막는다). 2차도 실패하면 1차를 쓴다.
        """
        wanted = {j.option_no for j in first.judgments if j.verdict is Verdict.INSUFFICIENT}
        queries = followup_queries(item, wanted)
        if not queries:
            return None
        try:
            extra = self._retrieval.retrieve_for(queries, config)
        except RetrievalFailedError:
            return None  # 2차는 보조 경로다. 실패해도 1차 답을 버리지 않는다
        known = {c.chunk_id for c in context}
        merged = list(context) + [c for c in extra[: config.k_opt] if c.chunk_id not in known]
        if len(merged) == len(context):
            return None
        try:
            model_answer = self._generator.generate(item, merged)
            second = Answer.from_model_output(
                model_answer,
                {c.chunk_id for c in merged},
                {c.chunk_id: c.location for c in merged},
            )
        except (ModelCallError, ModelTimeoutError, ModelOutputFormatError):
            return None
        log_event(
            log,
            "second_pass",
            options=sorted(wanted),
            added=len(merged) - len(context),
            adopted=second.evidence_sufficient,
        )
        if not second.evidence_sufficient:
            return None
        return (
            second,
            tuple(merged),
            model_answer.raw_output,
            tuple(q.effective for q in queries),
            len(merged) - len(context),
        )

    def _elapsed_ms(self, since: float) -> int:
        return round((self._timer() - since) * 1000)

    @staticmethod
    def _failed(outcome: Outcome, code: ErrorCode, exc: Exception) -> Answer:
        log_event(log, "answer_failed", code=code.value, error=f"{type(exc).__name__}: {exc}")
        message = RETRIEVAL_MESSAGE if outcome is Outcome.RETRIEVAL_ERROR else MODEL_MESSAGE
        return Answer.error(outcome, code, message)


def _exam_item(data: Mapping[str, Any]) -> ExamItem:
    if not isinstance(data, Mapping):
        raise InvalidExamItemError("input", '입력은 {"stem", "options"} 객체여야 합니다.')
    return ExamItem(stem=data.get("stem", ""), options=data.get("options", ()))


def _retrieval_code(exc: RetrievalFailedError) -> ErrorCode:
    if isinstance(exc, IndexNotReadyError):
        return ErrorCode.INDEX_NOT_READY
    if isinstance(exc, RerankerFailedError):
        return ErrorCode.RERANKER_FAILED
    return ErrorCode.RETRIEVAL_FAILED


def _retrieval_dict(result: RetrievalResult) -> dict[str, Any]:
    return {
        "options": [
            {
                "option_no": o.query.option_no,
                "candidates": [
                    {
                        "chunk_id": c.chunk_id,
                        "location": c.location,
                        "bm25_rank": c.bm25_rank,
                        "bm25_score": c.bm25_score,
                        "vector_rank": c.vector_rank,
                        "vector_score": c.vector_score,
                        "fused_rank": c.fused_rank,
                        "rerank_score": c.rerank_score,
                        "final_rank": c.final_rank,
                    }
                    for c in o.candidates
                ],
            }
            for o in result.options
        ],
        "question_list": [c.chunk_id for c in result.question_list()],
    }

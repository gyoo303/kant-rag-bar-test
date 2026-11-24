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
from lawqa.answering.domain.models import Answer, ErrorCode, Outcome
from lawqa.answering.domain.ports import AnswerGenerator
from lawqa.retrieval.application.retrieval_service import RetrievalService
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
        try:
            item = _exam_item(item_input)
            result = self._retrieval.retrieve(item, config)  # C+R 리라이트·fallback 포함
            context = tuple(result.context(config.k_opt))
            model_answer = self._generator.generate(item, context)
            raw_output = model_answer.raw_output
            answer = Answer.from_model_output(
                model_answer,
                {c.chunk_id for c in context},
                {c.chunk_id: c.location for c in context},
            )
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
        latency_ms = round((self._timer() - started) * 1000)
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
        )

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

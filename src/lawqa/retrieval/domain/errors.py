"""retrieval 도메인 예외 (04-interfaces-api §1.6, ADR-004). 표준 라이브러리만 사용."""

from __future__ import annotations


class InvalidExamItemError(ValueError):
    """입력 문항 규칙 위반(R-3). `field`는 잘못된 부분(`stem`, `options`, `options[3]`)."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


class RewriteFailedError(RuntimeError):
    """쿼리 리라이트 실패. 거부하지 않고 원 질의로 검색한다(INV-10)."""


class RetrievalFailedError(RuntimeError):
    """검색·재정렬 실패(infrastructure가 던짐). answering이 `RETRIEVAL_ERROR` 결과로 바꾼다."""


class IndexNotReadyError(RetrievalFailedError):
    """검색에 쓸 색인 판본이 없음(`INDEX_NOT_READY`)."""


class RerankerFailedError(RetrievalFailedError):
    """재정렬 모델 실패(`RERANKER_FAILED`)."""

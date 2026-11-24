"""검색 서비스 (04-interfaces-api §2·SEQ-03, ADR-011). DB 읽기만 한다.

문항 → 보기별 질의 5개(리라이트를 거쳤으면 그 질의) → 구성의 검색기로 보기마다 검색 →
`RetrievalResult`(보기별 목록 5개). 검색기 오류는 `RetrievalFailedError`로 올라간다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from lawqa.retrieval.domain.decomposer import QueryDecomposer
from lawqa.retrieval.domain.models import (
    ExamItem,
    OptionQuery,
    OptionResult,
    RetrievalConfig,
    RetrievalResult,
)
from lawqa.retrieval.domain.ports import OptionRetriever


class RetrievalService:
    def __init__(
        self,
        *,
        retriever_for: Callable[[RetrievalConfig], OptionRetriever],
        decomposer: QueryDecomposer | None = None,
    ) -> None:
        self._retriever_for = retriever_for
        self._decomposer = decomposer or QueryDecomposer()

    def decompose(self, item: ExamItem) -> list[OptionQuery]:
        """기본 보기별 질의 5개(리라이트 전, ADR-011)."""
        return self._decomposer.decompose(item)

    def retrieve(
        self,
        item: ExamItem,
        config: RetrievalConfig,
        queries: Sequence[OptionQuery] | None = None,
    ) -> RetrievalResult:
        """`queries`를 주면(리라이트 결과, C+R) 그것으로, 아니면 기본 분해로 검색한다."""
        option_queries = list(queries) if queries is not None else self._decomposer.decompose(item)
        retriever = self._retriever_for(config)
        return RetrievalResult(
            config_name=config.name,
            options=tuple(
                OptionResult(query=q, candidates=tuple(retriever.retrieve(q.effective)))
                for q in option_queries
            ),
        )

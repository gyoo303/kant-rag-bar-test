"""검색 서비스 (04-interfaces-api §2·SEQ-03, ADR-011, INV-10). DB 읽기만 한다.

문항 → 보기별 질의 5개 → (C+R이면) 리라이트 → 구성의 검색기로 보기마다 검색 →
`RetrievalResult`(보기별 목록 5개, 각 목록에 실제로 쓴 질의). 리라이트가 실패하면 모든 보기를
원 질의로 검색한다(`fallback=True`, 결과는 오류가 아님). 검색기 오류는 `RetrievalFailedError`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from lawqa.retrieval.domain.decomposer import QueryDecomposer
from lawqa.retrieval.domain.errors import RewriteFailedError
from lawqa.retrieval.domain.models import (
    Candidate,
    ExamItem,
    OptionQuery,
    OptionResult,
    RetrievalConfig,
    RetrievalResult,
)
from lawqa.retrieval.domain.ports import OptionRetriever, QueryRewriterPort
from lawqa.shared.logging_setup import log_event

log = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        *,
        retriever_for: Callable[[RetrievalConfig], OptionRetriever],
        rewriter: QueryRewriterPort | None = None,
        decomposer: QueryDecomposer | None = None,
    ) -> None:
        self._retriever_for = retriever_for
        self._rewriter = rewriter
        self._decomposer = decomposer or QueryDecomposer()

    def retrieve(self, item: ExamItem, config: RetrievalConfig) -> RetrievalResult:
        queries = self.queries_for(item, config)
        retriever = self._retriever_for(config)
        return RetrievalResult(
            config_name=config.name,
            options=tuple(
                OptionResult(query=q, candidates=tuple(retriever.retrieve(q.effective)))
                for q in queries
            ),
        )

    def retrieve_for(
        self, queries: Sequence[OptionQuery], config: RetrievalConfig
    ) -> list[Candidate]:
        """주어진 질의들로만 검색해 후보를 합친다 (CR-019 2차 검색).

        `RetrievalResult`를 만들지 않는다 — 보기 1~5 구조가 아니라 "모자란 명제 몇 개"이기 때문이다.
        질의 순서대로 라운드로빈으로 합치고 같은 청크는 처음 것만 남긴다(ADR-011과 같은 규칙).
        """
        retriever = self._retriever_for(config)
        lists = [retriever.retrieve(q.effective) for q in queries]
        merged: list[Candidate] = []
        seen: set[str] = set()
        depth = max((len(x) for x in lists), default=0)
        for rank in range(depth):
            for one in lists:
                if rank >= len(one):
                    continue
                candidate = one[rank]
                if candidate.chunk_id in seen:
                    continue
                seen.add(candidate.chunk_id)
                merged.append(candidate)
        return merged

    def queries_for(self, item: ExamItem, config: RetrievalConfig) -> list[OptionQuery]:
        """기본 분해, `use_rewrite`이면 리라이트(실패하면 모두 원 질의, INV-10)."""
        queries = self._decomposer.decompose(item)
        if not config.use_rewrite:
            return queries
        if self._rewriter is None:
            raise ValueError(f"구성 {config.name}은 리라이터가 필요합니다.")  # 조립 오류
        try:
            rewritten = self._rewriter.rewrite(item, queries)
        except RewriteFailedError as exc:
            log_event(log, "rewrite_fallback", scope="all", reason=type(exc).__name__)
            return [OptionQuery(q.option_no, q.original, None, fallback=True) for q in queries]
        partial = [q.option_no for q in rewritten if q.fallback]
        if partial:
            log_event(log, "rewrite_fallback", scope="partial", options=partial)
        return rewritten

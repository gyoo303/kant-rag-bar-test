"""retrieval 계약 (04-interfaces-api §1.3). 구현은 `retrieval.infrastructure`."""

from __future__ import annotations

from typing import Protocol

from lawqa.retrieval.domain.models import Candidate, ExamItem, OptionQuery


class OptionRetriever(Protocol):
    """보기 질의 하나 → `final_rank` 순 후보 목록(구성 A/B/C마다 구현)."""

    def retrieve(self, query: str) -> list[Candidate]: ...


class QueryRewriterPort(Protocol):
    """보기별 질의를 법률 용어 질의로 바꾼다(C+R). 실패하면 `RewriteFailedError`."""

    def rewrite(self, item: ExamItem, queries: list[OptionQuery]) -> list[OptionQuery]: ...

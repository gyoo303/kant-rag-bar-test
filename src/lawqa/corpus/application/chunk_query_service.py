"""청크·색인 판본 조회 (05-structure-conventions §1: retrieval·evaluation이 corpus를 읽는 통로)."""

from __future__ import annotations

from lawqa.corpus.domain.models import Chunk, IndexVersion
from lawqa.corpus.domain.ports import ChunkRepository, IndexVersionRepository, TransactionScope


class ChunkQueryService:
    def __init__(
        self,
        *,
        chunks: ChunkRepository,
        versions: IndexVersionRepository,
        tx: TransactionScope,
    ) -> None:
        self._chunks = chunks
        self._versions = versions
        self._tx = tx

    def list_chunks(self, index_version: str) -> list[Chunk]:
        """판본의 청크 전체(BM25 색인 구축용, ADR-009)."""
        with self._tx.transaction():
            return self._chunks.list_for_version(index_version)

    def get_chunks(self, index_version: str, chunk_ids: list[str]) -> list[Chunk]:
        with self._tx.transaction():
            return self._chunks.get_many(index_version, chunk_ids)

    def latest_complete_version(self) -> IndexVersion | None:
        """가장 최근 완료 판본(검색·`eval freeze --stage final`이 쓰는 판본)."""
        with self._tx.transaction():
            return self._versions.latest_complete()

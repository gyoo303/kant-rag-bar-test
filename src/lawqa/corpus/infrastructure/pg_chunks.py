"""`chunks` 저장소 (03-db-schema §3·§7, ADR-006). 커밋하지 않는다(응용 서비스가 트랜잭션 경계)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from lawqa.corpus.domain.models import Chunk, DocumentKind, SourceLocation

_COLUMNS = (
    "index_version",
    "chunk_id",
    "doc_id",
    "kind",
    "section",
    "seq",
    "location",
    "text",
    "referenced_articles",
    "bm25_tokens",
)
_INSERT_SQL = (
    f"INSERT INTO chunks ({', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * len(_COLUMNS))})"
)
_SELECT_SQL = f"SELECT {', '.join(_COLUMNS)} FROM chunks"
_ORDER = "ORDER BY doc_id, seq"


class PgChunkRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_for_version(self, index_version: str, chunks: list[Chunk]) -> int:
        """같은 판본의 청크를 모두 지우고 새로 넣는다. 다른 판본의 청크가 섞이면 거부."""
        others = {c.index_version for c in chunks} - {index_version}
        if others:
            raise ValueError(f"다른 판본의 청크가 섞여 있습니다: {sorted(others)}")
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE index_version = %s", (index_version,))
            if chunks:
                cur.executemany(_INSERT_SQL, [_chunk_values(c) for c in chunks])
        return len(chunks)

    def list_for_version(self, index_version: str) -> list[Chunk]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"{_SELECT_SQL} WHERE index_version = %s {_ORDER}", (index_version,))
            return [_row_to_chunk(row) for row in cur.fetchall()]

    def get_many(self, index_version: str, chunk_ids: list[str]) -> list[Chunk]:
        """요청한 chunk_id 순서대로 돌려준다(없는 ID는 빠짐)."""
        if not chunk_ids:
            return []
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"{_SELECT_SQL} WHERE index_version = %s AND chunk_id = ANY(%s)",
                (index_version, list(chunk_ids)),
            )
            found = {row["chunk_id"]: _row_to_chunk(row) for row in cur.fetchall()}
        return [found[cid] for cid in chunk_ids if cid in found]

    def count(self, index_version: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) FROM chunks WHERE index_version = %s", (index_version,)
        ).fetchone()
        return int(row[0]) if row else 0


def _chunk_values(chunk: Chunk) -> tuple[Any, ...]:
    return (
        chunk.index_version,
        chunk.chunk_id,
        chunk.doc_id,
        chunk.kind.value,
        chunk.section,
        chunk.seq,
        chunk.location.text,
        chunk.text,
        chunk.referenced_articles,
        list(chunk.bm25_tokens),
    )


def _row_to_chunk(row: Mapping[str, Any]) -> Chunk:
    return Chunk(
        index_version=row["index_version"],
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        kind=DocumentKind(row["kind"]),
        section=row["section"],
        seq=row["seq"],
        location=SourceLocation(row["location"]),
        text=row["text"],
        referenced_articles=row["referenced_articles"],
        bm25_tokens=tuple(row["bm25_tokens"] or ()),
    )

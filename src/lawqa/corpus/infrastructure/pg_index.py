"""`index_versions`·`import_issues` 저장소 (03-db-schema §3·§7, CR-007). 커밋하지 않는다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from lawqa.corpus.domain.models import ImportIssue, IndexVersion

_VERSION_COLUMNS = (
    "index_version",
    "corpus_version",
    "max_chars",
    "overlap_chars",
    "embedding_model",
    "embedding_dim",
    "doc_count",
    "chunk_count",
    "skipped_count",
    "complete",
    "created_at",
)


class PgIndexVersionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def save(self, version: IndexVersion) -> None:
        """판본 행을 넣는다. 같은 id가 있으면 값을 바꾼다(미완료 판본을 다시 만들 때)."""
        values = [getattr(version, c) for c in _VERSION_COLUMNS]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _VERSION_COLUMNS[1:])
        self._conn.execute(
            f"INSERT INTO index_versions ({', '.join(_VERSION_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_VERSION_COLUMNS))}) "
            f"ON CONFLICT (index_version) DO UPDATE SET {updates}",
            values,
        )

    def get(self, index_version: str) -> IndexVersion | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {', '.join(_VERSION_COLUMNS)} FROM index_versions "
                "WHERE index_version = %s",
                (index_version,),
            )
            row = cur.fetchone()
        return _row_to_version(row) if row else None

    def mark_complete(self, index_version: str, chunk_count: int, skipped: int) -> None:
        """청크 수·건너뛴 수를 기록한다. 건너뛴 것이 없을 때만 complete=true(REJ-06 "불완전")."""
        self._conn.execute(
            "UPDATE index_versions SET chunk_count = %s, skipped_count = %s, complete = %s "
            "WHERE index_version = %s",
            (chunk_count, skipped, skipped == 0, index_version),
        )

    def latest_complete(self) -> IndexVersion | None:
        """가장 최근에 만든 완료 판본(`eval freeze --stage final`용)."""
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {', '.join(_VERSION_COLUMNS)} FROM index_versions "
                "WHERE complete ORDER BY created_at DESC, index_version DESC LIMIT 1"
            )
            row = cur.fetchone()
        return _row_to_version(row) if row else None

    def latest_finished(self) -> IndexVersion | None:
        """끝까지 만들어진 가장 최근 판본(완료, 또는 건너뜀이 기록된 불완전). CR-008.

        중단된 판본은 `mark_complete` 전이라 `complete=false`·`skipped_count=0`이므로 빠진다.
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {', '.join(_VERSION_COLUMNS)} FROM index_versions "
                "WHERE complete OR skipped_count > 0 "
                "ORDER BY created_at DESC, index_version DESC LIMIT 1"
            )
            row = cur.fetchone()
        return _row_to_version(row) if row else None


class PgImportIssueRepository:
    """CR-007: 가져오기 문제는 corpus_version으로 묶는다(색인 판본보다 먼저 생기므로 FK 없음)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def add_many(self, issues: list[ImportIssue], corpus_version: str) -> None:
        if not issues:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO import_issues (corpus_version, source_file, source_line, reason) "
                "VALUES (%s, %s, %s, %s)",
                [(corpus_version, i.source_file, i.source_line, i.reason) for i in issues],
            )

    def count(self, corpus_version: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) FROM import_issues WHERE corpus_version = %s", (corpus_version,)
        ).fetchone()
        return int(row[0]) if row else 0

    def delete_for(self, corpus_version: str) -> None:
        """같은 원문을 다시 가져올 때 이전 문제 기록을 지운다(교체)."""
        self._conn.execute("DELETE FROM import_issues WHERE corpus_version = %s", (corpus_version,))

    def list_for(self, corpus_version: str) -> list[ImportIssue]:
        rows = self._conn.execute(
            "SELECT source_file, source_line, reason FROM import_issues "
            "WHERE corpus_version = %s ORDER BY id",
            (corpus_version,),
        ).fetchall()
        return [ImportIssue(r[0], r[1], r[2]) for r in rows]


def _row_to_version(row: Mapping[str, Any]) -> IndexVersion:
    return IndexVersion(**{column: row[column] for column in _VERSION_COLUMNS})

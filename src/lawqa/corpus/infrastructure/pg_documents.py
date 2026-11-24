"""`source_documents` 저장소 (03-db-schema §3·§7, ADR-006).

연결은 응용 서비스가 넘기고 트랜잭션도 응용 서비스가 연다. 이 클래스는 커밋하지 않는다.
psycopg 행은 이 모듈 밖으로 나가지 않는다(도메인 객체로 바꿔 돌려줌, RISK-16).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row

from lawqa.corpus.domain.models import DocumentKind, SourceDocument

_COLUMNS = (
    "doc_id",
    "kind",
    "title",
    "case_number",
    "decided_on",
    "court",
    "case_type",
    "holdings",
    "summary",
    "referenced_articles",
    "law_name",
    "article_no",
    "article_branch_no",
    "article_title",
    "body",
    "effective_on",
    "source_file",
    "source_line",
    "content_sha",
)
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS if c != "doc_id")
_UPSERT_SQL = (
    f"INSERT INTO source_documents ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))}) "
    f"ON CONFLICT (doc_id) DO UPDATE SET {_UPDATE_SET}, imported_at = now()"
)
_SELECT_SQL = f"SELECT {', '.join(_COLUMNS)} FROM source_documents"


class PgSourceDocumentRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(self, docs: list[SourceDocument]) -> int:
        """같은 doc_id는 덮어쓴다(멱등). 넣거나 바꾼 건수를 돌려준다."""
        if not docs:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, [_document_values(doc) for doc in docs])
        return len(docs)

    def iter_all(self, batch_size: int = 2000) -> Iterator[SourceDocument]:
        """doc_id 순으로 흘려 보낸다(서버 쪽 커서, 4만 건을 한꺼번에 메모리에 올리지 않음)."""
        with self._conn.cursor(name="source_documents_iter", row_factory=dict_row) as cur:
            cur.itersize = batch_size
            cur.execute(f"{_SELECT_SQL} ORDER BY doc_id")
            for row in cur:
                yield _row_to_document(row)

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) FROM source_documents").fetchone()
        return int(row[0]) if row else 0


def _document_values(doc: SourceDocument) -> tuple[Any, ...]:
    return tuple(
        doc.kind.value if column == "kind" else getattr(doc, column) for column in _COLUMNS
    )


def _row_to_document(row: Mapping[str, Any]) -> SourceDocument:
    values = dict(row)
    values["kind"] = DocumentKind(values["kind"])
    values["article_branch_no"] = values["article_branch_no"] or 0
    return SourceDocument(**values)

"""TKT-DB-M1-01: 스키마 반영과 제약 (03-db-schema §3, ADR-006, CR-007)."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

from lawqa.shared.db import init_schema

TABLES = {"source_documents", "index_versions", "chunks", "import_issues"}


def _insert_precedent(
    conn: psycopg.Connection, doc_id: str, holdings: str | None, summary: str | None
):
    conn.execute(
        """
        INSERT INTO source_documents
            (doc_id, kind, title, case_number, holdings, summary,
             source_file, source_line, content_sha)
        VALUES (%s, 'PRECEDENT', '사건명', '2016다215127', %s, %s, 'prec/1.json', 1, 'sha')
        """,
        (doc_id, holdings, summary),
    )


def _insert_statute(
    conn: psycopg.Connection, doc_id: str, body: str | None, article_no: int | None
):
    conn.execute(
        """
        INSERT INTO source_documents
            (doc_id, kind, title, law_name, article_no, body, source_file, source_line, content_sha)
        VALUES (%s, 'STATUTE_ARTICLE', '민법 제245조(점유로 인한 부동산소유권의 취득기간)', '민법',
                %s, %s, 'statutes/민법.txt', 10, 'sha')
        """,
        (doc_id, article_no, body),
    )


def _insert_index_version(conn: psycopg.Connection, index_version: str = "idx-aaaa-bbbb") -> None:
    conn.execute(
        """
        INSERT INTO index_versions
            (index_version, corpus_version, max_chars, overlap_chars,
             embedding_model, embedding_dim)
        VALUES (%s, 'corpus-sha', 1500, 150, 'text-embedding-3-small', 1536)
        """,
        (index_version,),
    )


def _insert_chunk(conn: psycopg.Connection, doc_id: str, seq: int = 1, section: str = "HOLDING"):
    conn.execute(
        """
        INSERT INTO chunks
            (index_version, chunk_id, doc_id, kind, section, seq, location, text, bm25_tokens)
        VALUES ('idx-aaaa-bbbb', %s, %s, 'PRECEDENT', %s, %s, '대법원 판결 [1]', '본문', %s)
        """,
        (f"{doc_id}#{section}#{seq}", doc_id, section, seq, ["점유", "취득시효"]),
    )


def test_init_schema_twice_on_fresh_db_no_error(db_conn: psycopg.Connection) -> None:
    init_schema(db_conn)
    init_schema(db_conn)

    rows = db_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    assert TABLES <= {name for (name,) in rows}


def test_init_schema_creates_vector_extension(db_conn: psycopg.Connection) -> None:
    row = db_conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()

    assert row is not None


def test_schema_has_no_pgvector_tables(db_conn: psycopg.Connection) -> None:
    """PGVector 표는 PGVector가 만든다(ADR-009). schema.sql은 만들지 않는다."""
    rows = db_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'langchain_pg_%'"
    ).fetchall()

    assert rows == []


@pytest.mark.parametrize(("holdings", "summary"), [(None, None), ("", "  "), ("   ", None)])
def test_precedent_without_holdings_and_summary_rejected(
    db_conn: psycopg.Connection, holdings: str | None, summary: str | None
) -> None:
    with pytest.raises(errors.CheckViolation, match="source_documents_precedent_content_check"):
        with db_conn.transaction():
            _insert_precedent(db_conn, "prec:1", holdings, summary)


@pytest.mark.parametrize(("holdings", "summary"), [("판시사항", None), (None, "판결요지")])
def test_precedent_with_holdings_or_summary_accepted(
    db_conn: psycopg.Connection, holdings: str | None, summary: str | None
) -> None:
    _insert_precedent(db_conn, "prec:2", holdings, summary)

    count = db_conn.execute("SELECT count(*) FROM source_documents").fetchone()[0]
    assert count == 1


@pytest.mark.parametrize(("body", "article_no"), [(None, 245), ("본문", None)])
def test_statute_without_body_or_article_no_rejected(
    db_conn: psycopg.Connection, body: str | None, article_no: int | None
) -> None:
    with pytest.raises(errors.CheckViolation, match="source_documents_statute_content_check"):
        with db_conn.transaction():
            _insert_statute(db_conn, "law:민법:245-0", body, article_no)


def test_statute_defaults_article_branch_no_to_zero(db_conn: psycopg.Connection) -> None:
    _insert_statute(db_conn, "law:민법:245-0", "본문", 245)

    branch = db_conn.execute(
        "SELECT article_branch_no FROM source_documents WHERE doc_id = 'law:민법:245-0'"
    ).fetchone()[0]
    assert branch == 0


def test_unknown_document_kind_rejected(db_conn: psycopg.Connection) -> None:
    with pytest.raises(errors.CheckViolation, match="source_documents_kind_check"):
        with db_conn.transaction():
            db_conn.execute(
                """
                INSERT INTO source_documents
                    (doc_id, kind, title, source_file, source_line, content_sha)
                VALUES ('x:1', 'OTHER', '제목', 'f', 1, 'sha')
                """
            )


def test_chunk_requires_existing_document_and_index_version(db_conn: psycopg.Connection) -> None:
    _insert_index_version(db_conn)

    with pytest.raises(errors.ForeignKeyViolation, match="chunks_doc_id_fkey"):
        with db_conn.transaction():
            _insert_chunk(db_conn, "prec:missing")


@pytest.mark.parametrize(
    ("seq", "section", "constraint"),
    [(0, "HOLDING", "chunks_seq_check"), (1, "OTHER", "chunks_section_check")],
)
def test_chunk_checks_reject_bad_values(
    db_conn: psycopg.Connection, seq: int, section: str, constraint: str
) -> None:
    _insert_index_version(db_conn)
    _insert_precedent(db_conn, "prec:3", "판시사항", None)

    with pytest.raises(errors.CheckViolation, match=constraint):
        with db_conn.transaction():
            _insert_chunk(db_conn, "prec:3", seq=seq, section=section)


def test_deleting_index_version_cascades_to_chunks(db_conn: psycopg.Connection) -> None:
    _insert_index_version(db_conn)
    _insert_precedent(db_conn, "prec:4", "판시사항", None)
    _insert_chunk(db_conn, "prec:4")

    db_conn.execute("DELETE FROM index_versions WHERE index_version = 'idx-aaaa-bbbb'")

    assert db_conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    assert db_conn.execute("SELECT count(*) FROM source_documents").fetchone()[0] == 1


def test_import_issue_saved_without_index_version(db_conn: psycopg.Connection) -> None:
    """CR-007: 가져오기 문제는 색인 판본 없이 corpus_version으로 저장된다."""
    db_conn.execute(
        """
        INSERT INTO import_issues (corpus_version, source_file, source_line, reason)
        VALUES ('corpus-sha', 'prec/9.json', 1, 'EMPTY_CONTENT')
        """
    )

    count = db_conn.execute(
        "SELECT count(*) FROM import_issues WHERE corpus_version = 'corpus-sha'"
    ).fetchone()[0]
    assert count == 1

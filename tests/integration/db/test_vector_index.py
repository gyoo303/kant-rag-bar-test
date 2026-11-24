"""TKT-DB-M2-02: PGVector 색인 어댑터 (ADR-009, 03-db-schema §3 ENT-05, GATE-10 근거).

PGVector는 자체 연결로 커밋하므로 시험마다 고유한 판본 이름을 쓰고 끝에 컬렉션을 지운다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.domain.models import Chunk, SourceDocument
from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader
from lawqa.corpus.infrastructure.vector_index import PgVectorIndex, sqlalchemy_url

RAW = Path(__file__).resolve().parents[2] / "fixtures" / "raw"
DIM = 1536


def _chunks(index_version: str) -> list[Chunk]:
    law = FileCollectorReader().read_law_text(RAW)
    assert law is not None
    statutes, _ = SourceDocument.statute_articles_from_text(law[1], law[0])
    policy = ChunkingPolicy(max_chars=1500, overlap_chars=150)
    return [c for d in statutes for c in policy.split(d, index_version, str.split)]


@pytest.fixture
def index(db_url: str, fresh_schema: None) -> PgVectorIndex:
    return PgVectorIndex(db_url, DeterministicFakeEmbedding(size=DIM), DIM)


@pytest.fixture
def version(index: PgVectorIndex) -> Iterator[str]:
    name = f"idx-test-{uuid.uuid4().hex[:8]}"
    yield name
    index.delete(name)


def test_sqlalchemy_url_uses_psycopg3_driver() -> None:
    assert sqlalchemy_url("postgresql://u:p@h:5433/db") == "postgresql+psycopg://u:p@h:5433/db"
    assert sqlalchemy_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    with pytest.raises(ValueError):
        sqlalchemy_url("mysql://u@h/db")


def test_count_is_zero_before_adding(index: PgVectorIndex, version: str) -> None:
    assert index.count(version) == 0


def test_add_chunks_count_equals_chunk_count(index: PgVectorIndex, version: str) -> None:
    chunks = _chunks(version)

    index.add_chunks(version, chunks, batch_size=4)

    assert index.count(version) == len(chunks) == 9


def test_add_same_chunks_twice_does_not_duplicate(index: PgVectorIndex, version: str) -> None:
    chunks = _chunks(version)

    index.add_chunks(version, chunks)
    index.add_chunks(version, chunks)

    assert index.count(version) == len(chunks)


def test_collection_name_ids_and_metadata_follow_rules(
    index: PgVectorIndex, version: str, db_conn
) -> None:
    chunks = _chunks(version)
    index.add_chunks(version, chunks)

    rows = db_conn.execute(
        "SELECT e.id, e.cmetadata, c.name FROM langchain_pg_embedding e "
        "JOIN langchain_pg_collection c ON e.collection_id = c.uuid WHERE c.name = %s",
        (f"chunks_{version}",),
    ).fetchall()
    by_id = {row[0]: row for row in rows}

    first = chunks[0]
    assert set(by_id) == {f"{version}/{c.chunk_id}" for c in chunks}
    assert by_id[f"{version}/{first.chunk_id}"][1] == {
        "chunk_id": first.chunk_id,
        "doc_id": first.doc_id,
        "kind": "STATUTE_ARTICLE",
        "section": "ARTICLE",
        "location": first.location.text,
        "index_version": version,
    }


def test_versions_are_separate_collections(index: PgVectorIndex, version: str) -> None:
    other = f"{version}-b"
    try:
        index.add_chunks(version, _chunks(version))
        index.add_chunks(other, _chunks(other)[:2])

        assert (index.count(version), index.count(other)) == (9, 2)
        index.delete(other)
        assert index.count(other) == 0 and index.count(version) == 9
    finally:
        index.delete(other)


def test_add_chunks_rejects_other_version(index: PgVectorIndex, version: str) -> None:
    with pytest.raises(ValueError, match="다른 판본"):
        index.add_chunks(version, _chunks("idx-other"))


def test_as_retriever_returns_chunk_ids(index: PgVectorIndex, version: str) -> None:
    chunks = _chunks(version)
    index.add_chunks(version, chunks)

    results = index.as_retriever(version, k=3).invoke(chunks[0].text)

    assert len(results) == 3
    assert results[0].metadata["chunk_id"] == chunks[0].chunk_id  # 같은 텍스트 → 같은 가짜 임베딩
    assert all(r.metadata["index_version"] == version for r in results)

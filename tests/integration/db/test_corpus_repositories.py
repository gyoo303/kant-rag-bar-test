"""TKT-DB-M2-01: 원문·청크·판본·이슈 저장소 (03-db-schema §3·§7, CR-007, AC-05-3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from psycopg import errors

from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.domain.errors import InvalidSourceDocumentError
from lawqa.corpus.domain.models import ImportIssue, IndexVersion, SourceDocument
from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader
from lawqa.corpus.infrastructure.pg_chunks import PgChunkRepository
from lawqa.corpus.infrastructure.pg_documents import PgSourceDocumentRepository
from lawqa.corpus.infrastructure.pg_index import PgImportIssueRepository, PgIndexVersionRepository

RAW = Path(__file__).resolve().parents[2] / "fixtures" / "raw"
POLICY = ChunkingPolicy(max_chars=1500, overlap_chars=150)


def _fixture_documents() -> list[SourceDocument]:
    reader = FileCollectorReader()
    docs: list[SourceDocument] = []
    for prec in reader.iter_prec_files(RAW):
        try:
            docs.append(SourceDocument.from_prec_service(prec.data or {}, prec.path))
        except InvalidSourceDocumentError:
            continue  # 형사 사건(범위 밖)은 건너뜀
    for statute in reader.iter_statute_texts(RAW):
        articles, _ = SourceDocument.statute_articles_from_text(
            statute.text, statute.path, statute.law_name
        )
        docs.extend(articles)
    return docs


def _version(index_version: str = "idx-aaaaaaaa-bbbbbbbb") -> IndexVersion:
    return IndexVersion(
        index_version=index_version,
        corpus_version="corpus-sha",
        max_chars=1500,
        overlap_chars=150,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        created_at=datetime(2026, 11, 25, 10, 0).astimezone(),
        doc_count=0,
    )


def _chunks(docs: list[SourceDocument], index_version: str):
    return [c for d in docs for c in POLICY.split(d, index_version, str.split)]


def test_fixtures_cover_precedents_and_statutes() -> None:
    docs = _fixture_documents()

    assert (
        sum(d.kind.value == "PRECEDENT" for d in docs) == 5
    )  # 7개 중 형사 1 제외, 지시문 판례 포함
    assert sum(d.kind.value == "STATUTE_ARTICLE" for d in docs) == 10  # 민법 9 + 상법 1 (CR-010)


def test_upsert_many_is_idempotent_and_updates_content(db_conn: psycopg.Connection) -> None:
    repo = PgSourceDocumentRepository(db_conn)
    docs = _fixture_documents()

    assert repo.upsert_many(docs) == len(docs)
    assert repo.upsert_many(docs) == len(docs)
    assert repo.count() == len(docs)

    changed = replace(docs[0], title="바뀐 사건명")
    repo.upsert_many([changed])
    stored = {d.doc_id: d for d in repo.iter_all()}
    assert stored[changed.doc_id].title == "바뀐 사건명"
    assert repo.count() == len(docs)


def test_iter_all_returns_equal_domain_objects(db_conn: psycopg.Connection) -> None:
    repo = PgSourceDocumentRepository(db_conn)
    docs = _fixture_documents()
    repo.upsert_many(docs)

    stored = list(repo.iter_all(batch_size=3))

    assert sorted(stored, key=lambda d: d.doc_id) == sorted(docs, key=lambda d: d.doc_id)
    assert all(isinstance(d, SourceDocument) for d in stored)


def test_index_version_save_get_and_mark_complete(db_conn: psycopg.Connection) -> None:
    repo = PgIndexVersionRepository(db_conn)
    version = _version()
    repo.save(version)
    repo.save(replace(version, doc_count=14))  # 같은 id 다시 저장 = 값 갱신

    assert repo.get(version.index_version) == replace(version, doc_count=14)
    assert repo.get("idx-none") is None

    repo.mark_complete(version.index_version, chunk_count=20, skipped=0)
    done = repo.get(version.index_version)
    assert done and done.complete and done.chunk_count == 20
    assert repo.latest_complete() == done

    repo.mark_complete(version.index_version, chunk_count=20, skipped=3)
    incomplete = repo.get(version.index_version)
    assert incomplete and not incomplete.complete and incomplete.skipped_count == 3
    assert repo.latest_complete() is None
    assert repo.latest_finished() == incomplete  # CR-008: 끝난 불완전 판본


def test_latest_finished_skips_interrupted_versions(db_conn: psycopg.Connection) -> None:
    repo = PgIndexVersionRepository(db_conn)
    repo.save(_version("idx-interrupted"))  # mark_complete 전 = 중단
    assert repo.latest_finished() is None
    repo.save(_version("idx-done"))
    repo.mark_complete("idx-done", chunk_count=5, skipped=0)
    finished = repo.latest_finished()
    assert finished is not None and finished.index_version == "idx-done"


def test_replace_for_version_replaces_only_that_version(db_conn: psycopg.Connection) -> None:
    docs = _fixture_documents()
    PgSourceDocumentRepository(db_conn).upsert_many(docs)
    versions = PgIndexVersionRepository(db_conn)
    versions.save(_version("idx-1"))
    versions.save(_version("idx-2"))
    repo = PgChunkRepository(db_conn)
    repo.replace_for_version("idx-2", _chunks(docs[:1], "idx-2"))

    first = _chunks(docs, "idx-1")
    assert repo.replace_for_version("idx-1", first) == len(first)
    assert repo.replace_for_version("idx-1", first[:3]) == 3

    assert repo.count("idx-1") == 3
    assert repo.count("idx-2") == len(_chunks(docs[:1], "idx-2"))
    with pytest.raises(ValueError, match="다른 판본"):
        repo.replace_for_version("idx-1", _chunks(docs[:1], "idx-2"))


def test_list_and_get_many_round_trip(db_conn: psycopg.Connection) -> None:
    docs = _fixture_documents()
    PgSourceDocumentRepository(db_conn).upsert_many(docs)
    PgIndexVersionRepository(db_conn).save(_version("idx-1"))
    repo = PgChunkRepository(db_conn)
    chunks = _chunks(docs, "idx-1")
    repo.replace_for_version("idx-1", chunks)

    listed = repo.list_for_version("idx-1")
    wanted = [chunks[2].chunk_id, chunks[0].chunk_id, "없는-id"]

    assert sorted(listed, key=lambda c: c.chunk_id) == sorted(chunks, key=lambda c: c.chunk_id)
    assert [c.chunk_id for c in repo.get_many("idx-1", wanted)] == wanted[:2]


def test_ac_05_3_same_input_twice_gives_same_chunk_id_set(db_conn: psycopg.Connection) -> None:
    PgSourceDocumentRepository(db_conn).upsert_many(_fixture_documents())
    PgIndexVersionRepository(db_conn).save(_version("idx-1"))
    repo = PgChunkRepository(db_conn)

    repo.replace_for_version("idx-1", _chunks(_fixture_documents(), "idx-1"))
    first = {c.chunk_id for c in repo.list_for_version("idx-1")}
    repo.replace_for_version("idx-1", _chunks(_fixture_documents(), "idx-1"))
    second = {c.chunk_id for c in repo.list_for_version("idx-1")}

    assert first == second and len(first) == repo.count("idx-1")


def test_chunk_for_unknown_document_rejected(db_conn: psycopg.Connection) -> None:
    PgIndexVersionRepository(db_conn).save(_version("idx-1"))
    chunks = _chunks(_fixture_documents()[:1], "idx-1")

    with pytest.raises(errors.ForeignKeyViolation):
        with db_conn.transaction():
            PgChunkRepository(db_conn).replace_for_version("idx-1", chunks)


def test_import_issues_grouped_by_corpus_version(db_conn: psycopg.Connection) -> None:
    repo = PgImportIssueRepository(db_conn)
    issues = [ImportIssue("prec/900011.json", 1, "MISSING_FIELD:사건번호")]

    repo.add_many(issues, "corpus-a")
    repo.add_many(issues * 2, "corpus-b")
    repo.add_many([], "corpus-a")

    assert (repo.count("corpus-a"), repo.count("corpus-b")) == (1, 2)
    assert repo.list_for("corpus-a") == issues
    repo.delete_for("corpus-b")
    assert repo.count("corpus-b") == 0 and repo.count("corpus-a") == 1

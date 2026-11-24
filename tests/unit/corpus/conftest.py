"""corpus 응용 서비스 시험용 가짜 저장소(DB·임베딩 없이, TKT-BE-M2-02)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from lawqa.corpus.domain.models import Chunk, ImportIssue, IndexVersion, SourceDocument


class FakeTx:
    def __init__(self) -> None:
        self.opened = 0

    def transaction(self) -> AbstractContextManager[Any]:
        self.opened += 1
        return nullcontext()


class FakeDocuments:
    def __init__(self) -> None:
        self.rows: dict[str, SourceDocument] = {}
        self.batches: list[int] = []

    def upsert_many(self, docs: list[SourceDocument]) -> int:
        self.batches.append(len(docs))
        for d in docs:
            self.rows[d.doc_id] = d
        return len(docs)

    def iter_all(self) -> Iterator[SourceDocument]:
        return iter(sorted(self.rows.values(), key=lambda d: d.doc_id))

    def count(self) -> int:
        return len(self.rows)


class FakeIssues:
    def __init__(self) -> None:
        self.rows: dict[str, list[ImportIssue]] = {}

    def add_many(self, issues: list[ImportIssue], corpus_version: str) -> None:
        self.rows.setdefault(corpus_version, []).extend(issues)

    def count(self, corpus_version: str) -> int:
        return len(self.rows.get(corpus_version, []))

    def delete_for(self, corpus_version: str) -> None:
        self.rows.pop(corpus_version, None)

    def list_for(self, corpus_version: str) -> list[ImportIssue]:
        return list(self.rows.get(corpus_version, []))


class FakeVersions:
    def __init__(self) -> None:
        self.rows: dict[str, IndexVersion] = {}

    def save(self, version: IndexVersion) -> None:
        self.rows[version.index_version] = version

    def get(self, index_version: str) -> IndexVersion | None:
        return self.rows.get(index_version)

    def mark_complete(self, index_version: str, chunk_count: int, skipped: int) -> None:
        self.rows[index_version] = replace(
            self.rows[index_version],
            chunk_count=chunk_count,
            skipped_count=skipped,
            complete=skipped == 0,  # 어댑터와 같음: 건너뜀이 있으면 불완전(REJ-06)
        )

    def latest_complete(self) -> IndexVersion | None:
        done = [v for v in self.rows.values() if v.complete]
        return max(done, key=lambda v: v.created_at) if done else None

    def latest_finished(self) -> IndexVersion | None:
        done = [v for v in self.rows.values() if v.complete or v.skipped_count > 0]
        return max(done, key=lambda v: v.created_at) if done else None


class FakeChunks:
    def __init__(self) -> None:
        self.rows: dict[str, list[Chunk]] = {}

    def replace_for_version(self, index_version: str, chunks: list[Chunk]) -> int:
        self.rows[index_version] = list(chunks)
        return len(chunks)

    def list_for_version(self, index_version: str) -> list[Chunk]:
        return list(self.rows.get(index_version, []))

    def get_many(self, index_version: str, chunk_ids: list[str]) -> list[Chunk]:
        wanted = set(chunk_ids)
        return [c for c in self.rows.get(index_version, []) if c.chunk_id in wanted]

    def count(self, index_version: str) -> int:
        return len(self.rows.get(index_version, []))


class FakeVectors:
    """`drop` 개를 빠뜨려 적재해 벡터 수 불일치를 흉내 낼 수 있다."""

    def __init__(self, drop: int = 0) -> None:
        self.rows: dict[str, dict[str, Chunk]] = {}
        self.add_calls = 0
        self.deleted: list[str] = []
        self._drop = drop

    def add_chunks(self, index_version: str, chunks: list[Chunk]) -> None:
        self.add_calls += 1
        kept = chunks[: len(chunks) - self._drop]
        self.rows.setdefault(index_version, {}).update({c.chunk_id: c for c in kept})

    def count(self, index_version: str) -> int:
        return len(self.rows.get(index_version, {}))

    def delete(self, index_version: str) -> None:
        self.deleted.append(index_version)
        self.rows.pop(index_version, None)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 24, 9, 0, tzinfo=UTC)


@pytest.fixture
def fake_tx() -> FakeTx:
    return FakeTx()


@pytest.fixture
def fake_documents() -> FakeDocuments:
    return FakeDocuments()


@pytest.fixture
def fake_issues() -> FakeIssues:
    return FakeIssues()


@pytest.fixture
def fake_versions() -> FakeVersions:
    return FakeVersions()


@pytest.fixture
def fake_chunks() -> FakeChunks:
    return FakeChunks()


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def fake_vectors() -> type[FakeVectors]:
    """`fake_vectors(drop=1)`처럼 새 가짜 벡터 색인을 만든다."""
    return FakeVectors

"""corpus 계약 (04-interfaces-api §1.2, 03-db-schema §7, CR-007). 구현은 `corpus.infrastructure`."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from lawqa.corpus.domain.models import Chunk, ImportIssue, IndexVersion, SourceDocument


@dataclass(frozen=True, slots=True)
class PrecFile:
    """판례 파일 1개. JSON이 깨졌으면 `data`가 None이고 `error`에 사유가 있다."""

    path: str  # raw_dir 기준 상대 경로(예: prec/123456.json)
    data: dict[str, Any] | None
    error: str | None = None


class CollectorReader(Protocol):
    def iter_prec_files(self, raw_dir: Path) -> Iterator[PrecFile]: ...
    def read_law_text(self, raw_dir: Path, name: str = "민법") -> tuple[str, str] | None: ...
    def list_law_files(self, raw_dir: Path) -> list[str]: ...


class Tokenizer(Protocol):
    def __call__(self, text: str) -> list[str]: ...


class SourceDocumentRepository(Protocol):
    def upsert_many(self, docs: list[SourceDocument]) -> int: ...
    def iter_all(self) -> Iterator[SourceDocument]: ...
    def count(self) -> int: ...


class IndexVersionRepository(Protocol):
    def save(self, version: IndexVersion) -> None: ...
    def get(self, index_version: str) -> IndexVersion | None: ...
    def mark_complete(self, index_version: str, chunk_count: int, skipped: int) -> None: ...


class ChunkRepository(Protocol):
    def replace_for_version(self, index_version: str, chunks: list[Chunk]) -> int: ...
    def list_for_version(self, index_version: str) -> list[Chunk]: ...
    def get_many(self, index_version: str, chunk_ids: list[str]) -> list[Chunk]: ...


class ImportIssueRepository(Protocol):
    """CR-007: 가져오기 문제는 corpus_version으로 묶는다."""

    def add_many(self, issues: list[ImportIssue], corpus_version: str) -> None: ...
    def count(self, corpus_version: str) -> int: ...
    def delete_for(self, corpus_version: str) -> None: ...


class VectorIndex(Protocol):
    def add_chunks(self, index_version: str, chunks: list[Chunk]) -> None: ...
    def count(self, index_version: str) -> int: ...

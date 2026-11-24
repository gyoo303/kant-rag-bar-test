"""가져오기 서비스 `corpus import` (US-05, ADR-015, SEQ-01, CR-007).

판례 `prec/*.json`과 법령 `statutes/*.txt` 전부를 원문 저장소에 넣는다(멱등, CR-009·010).
형식이 틀린 건은 건너뛰고
사유를 모은다(REJ-06). 삭제 조문·편장절 제목은 오류가 아니라 제외 건수다.
가져오기 문제 기록은 원문 판본(corpus_version)으로 묶어 교체 저장한다(CR-007).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lawqa.corpus.domain.errors import JSON_ERROR, InvalidSourceDocumentError
from lawqa.corpus.domain.models import ImportIssue, SourceDocument, corpus_version_of
from lawqa.corpus.domain.ports import (
    CollectorReader,
    ImportIssueRepository,
    SourceDocumentRepository,
    TransactionScope,
)

STATUTE_DIR = "statutes"
BATCH_SIZE = 500  # SEQ-01: 성공 문서 500건 = 트랜잭션 1


class MissingStatuteFileError(FileNotFoundError):
    """`statutes/`에 읽을 법령 텍스트가 하나도 없음(가져오기 입력 오류)."""


@dataclass(frozen=True, slots=True)
class ImportReport:
    imported: int
    issues: tuple[ImportIssue, ...]
    corpus_version: str
    excluded: dict[str, int] = field(default_factory=dict)
    ignored_files: tuple[str, ...] = ()

    @property
    def skipped(self) -> int:
        return len(self.issues)


class ImportService:
    def __init__(
        self,
        *,
        reader: CollectorReader,
        documents: SourceDocumentRepository,
        issues: ImportIssueRepository,
        tx: TransactionScope,
    ) -> None:
        self._reader = reader
        self._documents = documents
        self._issues = issues
        self._tx = tx

    def import_files(self, raw_dir: Path) -> ImportReport:
        issues: list[ImportIssue] = []
        imported = 0
        batch: list[SourceDocument] = []

        for prec in self._reader.iter_prec_files(raw_dir):
            if prec.data is None:
                issues.append(ImportIssue(prec.path, 1, JSON_ERROR))
                continue
            try:
                batch.append(SourceDocument.from_prec_service(prec.data, prec.path))
            except InvalidSourceDocumentError as exc:
                issues.append(ImportIssue(prec.path, 1, exc.reason))
                continue
            if len(batch) >= BATCH_SIZE:
                imported += self._save(batch)
                batch = []
        imported += self._save(batch)

        deleted = headings = dropped = 0
        statute_count = 0
        for statute in self._reader.iter_statute_texts(raw_dir):
            statute_count += 1
            articles, parse = SourceDocument.statute_articles_from_text(
                statute.text, statute.path, statute.law_name
            )
            issues.extend(parse.issues)
            deleted += parse.deleted
            headings += parse.headings
            dropped += parse.dropped_lines
            for start in range(0, len(articles), BATCH_SIZE):
                imported += self._save(articles[start : start + BATCH_SIZE])
        if statute_count == 0:
            raise MissingStatuteFileError(
                f"{raw_dir / STATUTE_DIR}에 읽을 법령 텍스트(*.txt)가 없습니다(ADR-015, CR-010)."
            )

        with self._tx.transaction():
            corpus_version = corpus_version_of(d.content_sha for d in self._documents.iter_all())
            self._issues.delete_for(corpus_version)
            self._issues.add_many(issues, corpus_version)

        return ImportReport(
            imported=imported,
            issues=tuple(issues),
            corpus_version=corpus_version,
            excluded={
                "deleted_articles": deleted,
                "heading_lines": headings,
                "orphan_lines": dropped,
            },
            ignored_files=tuple(self._reader.list_ignored_statute_files(raw_dir)),
        )

    def _save(self, docs: list[SourceDocument]) -> int:
        if not docs:
            return 0
        with self._tx.transaction():
            return self._documents.upsert_many(docs)

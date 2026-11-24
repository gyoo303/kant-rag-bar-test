"""TKT-BE-M2-02: 가져오기 서비스 (AC-05-4, ADR-015, SEQ-01, CR-007). 가짜 저장소로 시험한다."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lawqa.corpus.application import import_service
from lawqa.corpus.application.import_service import ImportService, MissingStatuteFileError
from lawqa.corpus.domain.errors import JSON_ERROR
from lawqa.corpus.domain.models import corpus_version_of
from lawqa.corpus.domain.ports import PrecFile
from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader

RAW = Path(__file__).resolve().parents[2] / "fixtures" / "raw"


def _service(reader, fake_documents, fake_issues, fake_tx) -> ImportService:
    return ImportService(reader=reader, documents=fake_documents, issues=fake_issues, tx=fake_tx)


def test_imports_precedents_and_statutes_and_records_issues(fake_documents, fake_issues, fake_tx):
    report = _service(FileCollectorReader(), fake_documents, fake_issues, fake_tx).import_files(RAW)

    assert report.imported == 15  # 판례 5 + 민법 조문 9 + 상법 조문 1 (CR-009·010)
    assert fake_documents.count() == 15
    assert [(i.source_file, i.reason) for i in report.issues] == [
        ("prec/900002.json", "OUT_OF_SCOPE")
    ]
    assert report.excluded["deleted_articles"] == 1
    assert report.ignored_files == ()  # statutes/의 *.txt는 더 이상 무시하지 않는다
    expected_cv = corpus_version_of(d.content_sha for d in fake_documents.rows.values())
    assert report.corpus_version == expected_cv
    assert fake_issues.count(expected_cv) == 1  # CR-007: 원문 판본으로 묶어 저장


def test_reimport_is_idempotent_and_replaces_issues(fake_documents, fake_issues, fake_tx):
    service = _service(FileCollectorReader(), fake_documents, fake_issues, fake_tx)
    first = service.import_files(RAW)
    second = service.import_files(RAW)

    assert second.corpus_version == first.corpus_version
    assert fake_documents.count() == 15
    assert fake_issues.count(second.corpus_version) == 1  # 쌓이지 않고 교체


def test_every_statute_file_is_imported_under_its_own_law_name(
    fake_documents, fake_issues, fake_tx
):
    """CR-009·010: `statutes/*.txt`를 전부 읽고 `doc_id`·`law_name`이 법령별로 갈린다."""
    _service(FileCollectorReader(), fake_documents, fake_issues, fake_tx).import_files(RAW)

    by_law: dict[str, int] = {}
    for doc in fake_documents.rows.values():
        if doc.law_name:
            by_law[doc.law_name] = by_law.get(doc.law_name, 0) + 1
    assert by_law == {"민법": 9, "상법": 1}

    commercial = fake_documents.rows["law:상법:1-0"]
    assert commercial.source_file == "statutes/상법.txt"
    assert commercial.location.text == "상법 제1조"


class _BrokenReader(FileCollectorReader):
    def iter_prec_files(self, raw_dir: Path) -> Iterator[PrecFile]:
        yield PrecFile("prec/1.json", None, "JSONDecodeError: …")


def test_broken_json_becomes_json_error_issue(fake_documents, fake_issues, fake_tx):
    report = _service(_BrokenReader(), fake_documents, fake_issues, fake_tx).import_files(RAW)

    assert ("prec/1.json", JSON_ERROR) in [(i.source_file, i.reason) for i in report.issues]
    assert report.skipped == 1


def test_missing_statute_file_is_input_error(fake_documents, fake_issues, fake_tx, tmp_path):
    with pytest.raises(MissingStatuteFileError):
        _service(FileCollectorReader(), fake_documents, fake_issues, fake_tx).import_files(tmp_path)


def test_saves_in_batches(fake_documents, fake_issues, fake_tx, monkeypatch):
    monkeypatch.setattr(import_service, "BATCH_SIZE", 2)
    _service(FileCollectorReader(), fake_documents, fake_issues, fake_tx).import_files(RAW)

    assert max(fake_documents.batches) == 2
    assert sum(fake_documents.batches) == 15

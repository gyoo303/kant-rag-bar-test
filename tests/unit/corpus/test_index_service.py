"""TKT-BE-M2-02: 색인 서비스 (AC-05-1·2, SEQ-02, GATE-10 출력 형식). 가짜 저장소로 시험한다."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lawqa.corpus.application.import_service import ImportService
from lawqa.corpus.application.index_service import IndexingError, IndexService
from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader

RAW = Path(__file__).resolve().parents[2] / "fixtures" / "raw"
POLICY = ChunkingPolicy(max_chars=1500, overlap_chars=150)
GATE_10 = re.compile(
    r"^index_version=idx-[0-9a-f]{8}-[0-9a-f]{8} chunks=\d+ embeddings=\d+ "
    r"skipped=\d+ complete=(true|false)$"
)


@pytest.fixture
def ctx(fake_documents, fake_issues, fake_versions, fake_chunks, fake_tx, fixed_clock):
    ImportService(
        reader=FileCollectorReader(), documents=fake_documents, issues=fake_issues, tx=fake_tx
    ).import_files(RAW)

    def make(vectors) -> IndexService:
        return IndexService(
            documents=fake_documents,
            chunks=fake_chunks,
            versions=fake_versions,
            issues=fake_issues,
            vectors=vectors,
            tokenizer=str.split,
            tx=fake_tx,
            clock=fixed_clock,
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
        )

    return make


def test_skipped_imports_leave_index_incomplete(ctx, fake_chunks, fake_versions, fake_vectors):
    result = ctx(fake_vectors()).build_index(POLICY)

    v = result.version
    assert v.chunk_count == fake_chunks.count(v.index_version) == result.embeddings > 0
    assert v.doc_count == 14
    assert v.skipped_count == 1
    assert not v.complete  # AC-05-4: 건너뛴 가져오기 건 → "불완전"
    assert fake_versions.latest_complete() is None
    assert all(c.bm25_tokens for c in fake_chunks.list_for_version(v.index_version))


def test_no_skips_marks_complete(ctx, fake_issues, fake_versions, fake_vectors):
    fake_issues.rows.clear()
    result = ctx(fake_vectors()).build_index(POLICY)

    assert result.version.complete
    assert result.version.skipped_count == 0
    assert fake_versions.latest_complete() == result.version


def test_summary_line_matches_gate_10(ctx, fake_vectors):
    line = ctx(fake_vectors()).build_index(POLICY).summary_line()
    assert GATE_10.match(line), line
    assert line.endswith("skipped=1 complete=false")


def test_rerun_same_version_is_already_existing(ctx, fake_vectors):
    vectors = fake_vectors()
    first = ctx(vectors).build_index(POLICY)
    second = ctx(vectors).build_index(POLICY)

    assert second.already_existed  # 불완전으로 끝난 판본도 다시 임베딩하지 않음
    assert second.version.index_version == first.version.index_version
    assert vectors.add_calls == 1


def test_rerun_complete_version_is_already_existing(ctx, fake_issues, fake_vectors):
    fake_issues.rows.clear()
    vectors = fake_vectors()
    ctx(vectors).build_index(POLICY)
    assert ctx(vectors).build_index(POLICY).already_existed
    assert vectors.add_calls == 1


def test_different_chunking_makes_new_version(ctx, fake_vectors):
    vectors = fake_vectors()
    a = ctx(vectors).build_index(POLICY)
    b = ctx(vectors).build_index(ChunkingPolicy(max_chars=800, overlap_chars=100))
    assert a.version.index_version != b.version.index_version


def test_vector_count_mismatch_leaves_version_incomplete(ctx, fake_versions, fake_vectors):
    with pytest.raises(IndexingError):
        ctx(fake_vectors(drop=1)).build_index(POLICY)
    (version,) = fake_versions.rows.values()
    assert not version.complete
    assert fake_versions.latest_complete() is None


def test_incomplete_version_is_rebuilt_from_scratch(ctx, fake_vectors):
    with pytest.raises(IndexingError):
        ctx(fake_vectors(drop=1)).build_index(POLICY)
    vectors = fake_vectors()
    result = ctx(vectors).build_index(POLICY)
    assert not result.already_existed  # 중단된 판본은 처음부터 다시 만든다
    assert result.embeddings == result.version.chunk_count
    assert vectors.deleted == [result.version.index_version]


def test_empty_corpus_is_error(
    fake_documents, fake_issues, fake_versions, fake_chunks, fake_tx, fixed_clock, fake_vectors
):
    service = IndexService(
        documents=fake_documents,
        chunks=fake_chunks,
        versions=fake_versions,
        issues=fake_issues,
        vectors=fake_vectors(),
        tokenizer=str.split,
        tx=fake_tx,
        clock=fixed_clock,
        embedding_model="m",
        embedding_dim=8,
    )
    with pytest.raises(IndexingError):
        service.build_index(POLICY)

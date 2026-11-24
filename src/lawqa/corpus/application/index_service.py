"""색인 서비스 `corpus index` (US-05, SEQ-02, §9.2, GATE-10).

원문 저장소 전체 → 청킹(Kiwi 토큰) → 청크 표 교체(트랜잭션 1) → 벡터 적재 → 벡터 수 = 청크 수 확인
→ 완료 표시(트랜잭션 2, 건너뛴 가져오기 건이 있으면 "불완전").
같은 판본이 이미 완료면 다시 만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.domain.models import Chunk, IndexVersion, corpus_version_of
from lawqa.corpus.domain.ports import (
    ChunkRepository,
    ImportIssueRepository,
    IndexVersionRepository,
    SourceDocumentRepository,
    Tokenizer,
    TransactionScope,
    VectorIndex,
)
from lawqa.shared.clock import Clock


class IndexingError(RuntimeError):
    """색인을 끝내지 못함(문서 없음, 벡터 수 불일치)."""


@dataclass(frozen=True, slots=True)
class IndexResult:
    version: IndexVersion
    embeddings: int
    already_existed: bool

    def summary_line(self) -> str:
        """GATE-10 출력 형식(04-interfaces-api API-03)."""
        v = self.version
        return (
            f"index_version={v.index_version} chunks={v.chunk_count} embeddings={self.embeddings} "
            f"skipped={v.skipped_count} complete={'true' if v.complete else 'false'}"
        )


class IndexService:
    def __init__(
        self,
        *,
        documents: SourceDocumentRepository,
        chunks: ChunkRepository,
        versions: IndexVersionRepository,
        issues: ImportIssueRepository,
        vectors: VectorIndex,
        tokenizer: Tokenizer | Callable[[str], list[str]],
        tx: TransactionScope,
        clock: Clock,
        embedding_model: str,
        embedding_dim: int,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._versions = versions
        self._issues = issues
        self._vectors = vectors
        self._tokenizer = tokenizer
        self._tx = tx
        self._clock = clock
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim

    def build_index(self, policy: ChunkingPolicy) -> IndexResult:
        with self._tx.transaction():
            documents = list(self._documents.iter_all())
        if not documents:
            raise IndexingError("원문 저장소가 비어 있습니다. 먼저 corpus import를 실행하세요.")
        corpus_version = corpus_version_of(d.content_sha for d in documents)
        version_id = IndexVersion.compute_id(
            corpus_version, policy, self._embedding_model, self._embedding_dim
        )

        existing = self._versions.get(version_id)
        if existing is not None:
            embeddings = self._vectors.count(version_id)
            if self._finished(existing, embeddings):
                return IndexResult(existing, embeddings, already_existed=True)

        chunks: list[Chunk] = [
            c for d in documents for c in policy.split(d, version_id, self._tokenizer)
        ]
        with self._tx.transaction():
            self._versions.save(
                IndexVersion(
                    index_version=version_id,
                    corpus_version=corpus_version,
                    max_chars=policy.max_chars,
                    overlap_chars=policy.overlap_chars,
                    embedding_model=self._embedding_model,
                    embedding_dim=self._embedding_dim,
                    created_at=self._clock.now(),
                    doc_count=len(documents),
                    chunk_count=len(chunks),
                )
            )
            self._chunks.replace_for_version(version_id, chunks)

        self._vectors.delete(version_id)  # 미완료 판본을 다시 만들 때 남은 벡터를 지움
        self._vectors.add_chunks(version_id, chunks)
        embeddings = self._vectors.count(version_id)
        if embeddings != len(chunks):
            raise IndexingError(
                f"벡터 수 {embeddings}가 청크 수 {len(chunks)}와 다릅니다(GATE-10)."
            )

        with self._tx.transaction():
            skipped = self._issues.count(corpus_version)
            self._versions.mark_complete(version_id, len(chunks), skipped)
            done = self._versions.get(version_id)
        if done is None:
            raise IndexingError(f"색인 판본 {version_id}를 다시 읽지 못했습니다.")
        return IndexResult(done, embeddings, already_existed=False)

    @staticmethod
    def _finished(version: IndexVersion, embeddings: int) -> bool:
        """끝까지 만들어진 판본인가. 건너뛴 가져오기 건이 있어 `complete=false`(불완전)로 끝난
        판본도 다시 임베딩하지 않는다(벡터 수 = 청크 수이고 건너뜀 수가 기록된 경우).
        """
        if version.complete:
            return True
        return version.skipped_count > 0 and embeddings == version.chunk_count > 0

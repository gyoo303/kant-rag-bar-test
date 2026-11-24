"""PGVector 색인 어댑터 (ADR-009, 03-db-schema §3 ENT-05·§7, 스택 주의 S-03).

- 벡터 표(`langchain_pg_collection`, `langchain_pg_embedding`)는 PGVector가 만든다
  (schema.sql에 없음).
- 컬렉션 이름 `chunks_<index_version>`, 문서 ID = `<index_version>/<chunk_id>`
  (`langchain_pg_embedding.id`는 컬렉션을 가리지 않는 기본 키라, 판본이 달라도 같은 chunk_id가
  충돌한다 — 시험으로 확인).
- 메타데이터 = `{chunk_id, doc_id, kind, section, location, index_version}`.
- PGVector는 자체 SQLAlchemy 엔진으로 접속하고 스스로 커밋한다(04-interfaces-api §10).
  그래서 색인 완료 표시는 적재가 끝난 뒤 별도 트랜잭션에서 한다(SEQ-02).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_postgres import PGVector

from lawqa.corpus.domain.models import Chunk, collection_name_for

DEFAULT_BATCH = 100  # 04-interfaces-api §10: 임베딩 묶음 100개


def sqlalchemy_url(database_url: str) -> str:
    """`postgresql://…`를 psycopg 3 드라이버 SQLAlchemy URL로 바꾼다(S-03)."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix) :]
    raise ValueError("DATABASE_URL은 postgresql:// 로 시작해야 합니다.")


def vector_id(index_version: str, chunk_id: str) -> str:
    """벡터 문서 ID. 판본마다 따로 두려고 판본을 앞에 붙인다(청크 ID는 메타데이터 `chunk_id`)."""
    return f"{index_version}/{chunk_id}"


def chunk_metadata(chunk: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "kind": chunk.kind.value,
        "section": chunk.section,
        "location": chunk.location.text,
        "index_version": chunk.index_version,
    }


class PgVectorIndex:
    """`VectorIndex` 계약 구현.

    임베딩 모델은 밖에서 주입한다(운영: OpenAIEmbeddings, 시험: 가짜).
    """

    def __init__(self, database_url: str, embeddings: Embeddings, embedding_dim: int) -> None:
        self._database_url = database_url
        self._sqlalchemy_url = sqlalchemy_url(database_url)
        self._embeddings = embeddings
        self._embedding_dim = embedding_dim

    def add_chunks(
        self, index_version: str, chunks: Sequence[Chunk], batch_size: int = DEFAULT_BATCH
    ) -> None:
        """청크를 묶음 단위로 임베딩·저장한다. 같은 chunk_id는 덮어쓴다."""
        others = {c.index_version for c in chunks} - {index_version}
        if others:
            raise ValueError(f"다른 판본의 청크가 섞여 있습니다: {sorted(others)}")
        store = self._store(index_version)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            store.add_documents(
                [Document(page_content=c.text, metadata=chunk_metadata(c)) for c in batch],
                ids=[vector_id(index_version, c.chunk_id) for c in batch],
            )

    def delete(self, index_version: str) -> None:
        """판본의 컬렉션과 벡터를 모두 지운다(미완료 판본을 처음부터 다시 만들 때, SEQ-02)."""
        self._store(index_version).delete_collection()

    def count(self, index_version: str) -> int:
        """판본 컬렉션의 벡터 수(GATE-10: 청크 수와 같아야 함). 컬렉션이 없으면 0."""
        with psycopg.connect(self._database_url) as conn:
            if not _tables_exist(conn):
                return 0
            row = conn.execute(
                "SELECT count(*) FROM langchain_pg_embedding e "
                "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                "WHERE c.name = %s",
                (collection_name_for(index_version),),
            ).fetchone()
        return int(row[0]) if row else 0

    def as_retriever(self, index_version: str, k: int) -> BaseRetriever:
        """구성 A의 벡터 검색기(ADR-009). 결과의 청크 ID는 `metadata["chunk_id"]`."""
        return self._store(index_version).as_retriever(search_kwargs={"k": k})

    def _store(self, index_version: str) -> PGVector:
        return PGVector(
            embeddings=self._embeddings,
            connection=self._sqlalchemy_url,
            embedding_length=self._embedding_dim,
            collection_name=collection_name_for(index_version),
            use_jsonb=True,
            create_extension=False,  # vector 확장은 init_schema가 만든다(ADR-006)
        )


def _tables_exist(conn: psycopg.Connection) -> bool:
    row = conn.execute("SELECT to_regclass('langchain_pg_embedding') IS NOT NULL").fetchone()
    return bool(row and row[0])

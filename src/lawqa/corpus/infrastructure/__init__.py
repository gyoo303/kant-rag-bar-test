"""corpus 외부 연결(저장소·모델·파일)과 조립 함수(CONV-03 `build_*`).

연결(`psycopg.Connection`)은 진입점이 열고 닫는다(명령 1회 = 연결 1개, 04-interfaces-api §10).
"""

from __future__ import annotations

import psycopg
from langchain_core.embeddings import Embeddings

from lawqa.corpus.application.chunk_query_service import ChunkQueryService
from lawqa.corpus.application.import_service import ImportService
from lawqa.corpus.application.index_service import IndexService
from lawqa.corpus.domain.chunking import ChunkingPolicy
from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader
from lawqa.corpus.infrastructure.kiwi_tokenizer import KiwiTokenizer
from lawqa.corpus.infrastructure.pg_chunks import PgChunkRepository
from lawqa.corpus.infrastructure.pg_documents import PgSourceDocumentRepository
from lawqa.corpus.infrastructure.pg_index import PgImportIssueRepository, PgIndexVersionRepository
from lawqa.corpus.infrastructure.vector_index import PgVectorIndex
from lawqa.shared.clock import Clock, SystemClock
from lawqa.shared.settings import Settings

EMBEDDING_MAX_RETRIES = 3  # 04-interfaces-api §10: 외부 호출 재시도 3회


def openai_embeddings(settings: Settings) -> Embeddings:
    """운영 임베딩 모델(ADR-008: text-embedding-3-small, 1536차원)."""
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.models.embedding,
        dimensions=settings.models.embedding_dim,
        api_key=settings.secrets.require("openai_api_key"),
        max_retries=EMBEDDING_MAX_RETRIES,
    )


def chunking_policy(settings: Settings) -> ChunkingPolicy:
    return ChunkingPolicy(
        max_chars=settings.chunking.max_chars, overlap_chars=settings.chunking.overlap_chars
    )


def build_import_service(conn: psycopg.Connection) -> ImportService:
    return ImportService(
        reader=FileCollectorReader(),
        documents=PgSourceDocumentRepository(conn),
        issues=PgImportIssueRepository(conn),
        tx=conn,
    )


def build_index_service(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    database_url: str,
    embeddings: Embeddings | None = None,
    clock: Clock | None = None,
) -> IndexService:
    """`database_url`은 `conn`과 같은 DB(PGVector가 자체 연결로 쓴다, §10).

    `embeddings`를 넘기지 않으면 OpenAI 임베딩을 쓴다(시험은 가짜를 넘긴다).
    """
    return IndexService(
        documents=PgSourceDocumentRepository(conn),
        chunks=PgChunkRepository(conn),
        versions=PgIndexVersionRepository(conn),
        issues=PgImportIssueRepository(conn),
        vectors=PgVectorIndex(
            database_url,
            embeddings if embeddings is not None else openai_embeddings(settings),
            settings.models.embedding_dim,
        ),
        tokenizer=KiwiTokenizer(),
        tx=conn,
        clock=clock if clock is not None else SystemClock(),
        embedding_model=settings.models.embedding,
        embedding_dim=settings.models.embedding_dim,
    )


def build_chunk_query_service(conn: psycopg.Connection) -> ChunkQueryService:
    return ChunkQueryService(
        chunks=PgChunkRepository(conn),
        versions=PgIndexVersionRepository(conn),
        tx=conn,
    )

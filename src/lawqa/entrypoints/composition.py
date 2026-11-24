"""여러 모듈의 infrastructure를 엮는 조립 (진입점 전용).

모듈끼리는 서로의 infrastructure를 import할 수 없으므로(05-structure-conventions §4) `ask`·
`eval run`·Streamlit이 함께 쓰는 조립은 진입점 패키지에 둔다. 무거운 자원(BM25 색인·재정렬 모델)은
`AnswerService` 안의 검색기 공장이 처음 쓸 때 한 번 만든다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from langchain_community.cross_encoders import BaseCrossEncoder
from langchain_core.embeddings import Embeddings

from lawqa.answering.application.answer_service import AnswerService
from lawqa.answering.domain.ports import AnswerGenerator
from lawqa.answering.infrastructure import build_generator
from lawqa.corpus.domain.models import IndexVersion
from lawqa.corpus.infrastructure import build_chunk_query_service, openai_embeddings
from lawqa.corpus.infrastructure.kiwi_tokenizer import KiwiTokenizer
from lawqa.corpus.infrastructure.vector_index import sqlalchemy_url
from lawqa.retrieval.domain.models import RetrievalConfig
from lawqa.retrieval.infrastructure import build_retrieval_service, retrieval_config
from lawqa.shared.settings import RUN_CONFIGS, Settings, load_settings


@dataclass(frozen=True, slots=True)
class AnswerRuntime:
    service: AnswerService
    index_version: IndexVersion | None

    def index_warning(self) -> str | None:
        """검색 판본이 없거나 불완전이면 경고 문구(CR-008)."""
        v = self.index_version
        if v is None:
            return "검색할 색인 판본이 없습니다. corpus import·index를 먼저 실행하세요."
        if not v.complete:
            return (
                f"불완전 색인 {v.index_version}로 검색합니다(가져오기 건너뜀 {v.skipped_count}건). "
                "본 평가 고정에는 쓸 수 없습니다."
            )
        return None


def run_configs() -> dict[str, RetrievalConfig]:
    return {name: retrieval_config(load_settings(name)) for name in RUN_CONFIGS}


def build_answer_runtime(
    conn: psycopg.Connection,
    database_url: str,
    *,
    settings: Settings | None = None,
    embeddings: Embeddings | None = None,
    cross_encoder: Callable[[], BaseCrossEncoder] | None = None,
    generator: AnswerGenerator | None = None,
) -> AnswerRuntime:
    """`conn`은 프로세스가 살아 있는 동안 열어 둔다(검색기가 청크를 처음 쓸 때 읽음)."""
    base = settings or load_settings("base")
    chunks = build_chunk_query_service(conn)
    version = chunks.search_version()
    retrieval = build_retrieval_service(
        chunks,
        base,
        index_version=version.index_version if version else None,
        sqlalchemy_url=sqlalchemy_url(database_url),
        embeddings=embeddings or openai_embeddings(base),
        tokenize=KiwiTokenizer(),
        cross_encoder=cross_encoder,
    )
    service = AnswerService(
        retrieval=retrieval,
        generator=generator or build_generator(base),
        configs=run_configs(),
    )
    return AnswerRuntime(service=service, index_version=version)

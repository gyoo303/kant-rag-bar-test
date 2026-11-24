"""retrieval 외부 연결(LangChain 검색기)과 조립 함수(CONV-03 `build_*`).

다른 모듈의 infrastructure는 import하지 않는다(05-structure-conventions §4): 청크는
`corpus.application.ChunkQueryService`로 받고, Kiwi 토큰화·임베딩 모델은 진입점이 넘긴다.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_community.cross_encoders import BaseCrossEncoder
from langchain_core.embeddings import Embeddings

from lawqa.corpus.application.chunk_query_service import ChunkQueryService
from lawqa.retrieval.application.retrieval_service import RetrievalService
from lawqa.retrieval.domain.errors import RetrievalFailedError
from lawqa.retrieval.domain.models import RetrievalConfig, RetrievalMode
from lawqa.retrieval.domain.ports import OptionRetriever
from lawqa.retrieval.infrastructure.reranker import (
    RerankOptionRetriever,
    huggingface_cross_encoder,
    resolve_device,
)
from lawqa.retrieval.infrastructure.retrievers import (
    Bm25Search,
    HybridOptionRetriever,
    VectorOptionRetriever,
    VectorSearch,
)
from lawqa.shared.settings import Settings


def retrieval_config(settings: Settings) -> RetrievalConfig:
    """구성 설정(`A`·`B`·`C`·`C+R`)에서 검색 구성을 만든다. `base`는 구성이 아니라 거부."""
    r = settings.retrieval
    return RetrievalConfig(
        name=settings.config_name,  # type: ignore[arg-type]  # RetrievalConfig가 검사
        mode=RetrievalMode(settings.run.mode),
        use_rewrite=settings.run.use_rewrite,
        n_vec=r.n_vec,
        n_bm25=r.n_bm25,
        n_fuse=r.n_fuse,
        k_opt=r.k_opt,
        rrf_c=r.rrf_c,
        weights=r.weights,
    )


class RetrieverFactory:
    """색인 판본 하나의 검색기를 만든다. BM25 색인·PGVector 연결은 처음 쓸 때 한 번 만든다."""

    def __init__(
        self,
        *,
        chunks: ChunkQueryService,
        index_version: str,
        sqlalchemy_url: str,
        embeddings: Embeddings,
        embedding_dim: int,
        tokenize: Callable[[str], list[str]],
        cross_encoder: Callable[[], BaseCrossEncoder] | None = None,
    ) -> None:
        self._chunks = chunks
        self._index_version = index_version
        self._sqlalchemy_url = sqlalchemy_url
        self._embeddings = embeddings
        self._embedding_dim = embedding_dim
        self._tokenize = tokenize
        self._cross_encoder_factory = cross_encoder
        self._encoder: BaseCrossEncoder | None = None
        self._bm25: Bm25Search | None = None
        self._vector: VectorSearch | None = None
        self._built: dict[tuple[object, ...], OptionRetriever] = {}

    def __call__(self, config: RetrievalConfig) -> OptionRetriever:
        key = (config.mode, config.comparable_key)
        if key not in self._built:
            self._built[key] = self._build(config)
        return self._built[key]

    def _build(self, config: RetrievalConfig) -> OptionRetriever:
        if config.mode is RetrievalMode.A:
            return VectorOptionRetriever(self._vector_search(), config)
        if config.mode is RetrievalMode.B:
            return HybridOptionRetriever(self._bm25_search(), self._vector_search(), config)
        encoder = self._cross_encoder()  # 모델이 없으면 DB에 연결하기 전에 실패
        hybrid = HybridOptionRetriever(self._bm25_search(), self._vector_search(), config)
        return RerankOptionRetriever(hybrid, encoder, config)

    def _cross_encoder(self) -> BaseCrossEncoder:
        if self._encoder is None:
            if self._cross_encoder_factory is None:
                raise RetrievalFailedError("재정렬 모델이 주어지지 않았습니다(구성 C).")
            self._encoder = self._cross_encoder_factory()
        return self._encoder

    def _vector_search(self) -> VectorSearch:
        if self._vector is None:
            self._vector = VectorSearch(
                self._sqlalchemy_url, self._embeddings, self._embedding_dim, self._index_version
            )
        return self._vector

    def _bm25_search(self) -> Bm25Search:
        if self._bm25 is None:
            self._bm25 = Bm25Search(self._chunks.list_chunks(self._index_version), self._tokenize)
        return self._bm25


def build_retrieval_service(
    chunks: ChunkQueryService,
    settings: Settings,
    *,
    index_version: str,
    sqlalchemy_url: str,
    embeddings: Embeddings,
    tokenize: Callable[[str], list[str]],
    cross_encoder: Callable[[], BaseCrossEncoder] | None = None,
) -> RetrievalService:
    """진입점(`ask`·`eval run`·Streamlit)이 판본·임베딩·토큰화를 골라 넘긴다.

    `cross_encoder`를 넘기지 않으면 설정의 재정렬 모델(`reranker`, `reranker_device`)을
    구성 C를 처음 쓸 때 한 번 적재한다.
    """
    models = settings.models
    encoder = cross_encoder or (
        lambda: huggingface_cross_encoder(models.reranker, resolve_device(models.reranker_device))
    )
    return RetrievalService(
        retriever_for=RetrieverFactory(
            chunks=chunks,
            index_version=index_version,
            sqlalchemy_url=sqlalchemy_url,
            embeddings=embeddings,
            embedding_dim=settings.models.embedding_dim,
            tokenize=tokenize,
            cross_encoder=encoder,
        )
    )

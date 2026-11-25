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
from lawqa.retrieval.domain.errors import IndexNotReadyError, RetrievalFailedError
from lawqa.retrieval.domain.models import RetrievalConfig, RetrievalMode
from lawqa.retrieval.domain.ports import OptionRetriever, QueryRewriterPort
from lawqa.retrieval.infrastructure.reranker import (
    RerankOptionRetriever,
    huggingface_cross_encoder,
    resolve_device,
)
from lawqa.retrieval.infrastructure.retrievers import (
    STATUTE_KIND,
    Bm25Search,
    HybridOptionRetriever,
    StatuteQuotaRetriever,
    VectorOptionRetriever,
    VectorSearch,
)
from lawqa.retrieval.infrastructure.rewriter import OpenAIQueryRewriter, RewritePrompt
from lawqa.retrieval.infrastructure.rewriter import chat_model as rewrite_chat_model
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
        k_law=r.k_law,  # CR-018
        rrf_c=r.rrf_c,
        weights=r.weights,
    )


class RetrieverFactory:
    """색인 판본 하나의 검색기를 만든다. BM25 색인·PGVector 연결은 처음 쓸 때 한 번 만든다."""

    def __init__(
        self,
        *,
        chunks: ChunkQueryService,
        index_version: str | None,
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
        if self._index_version is None:
            raise IndexNotReadyError(
                "검색할 색인 판본이 없습니다. corpus import·index를 먼저 실행하세요."
            )
        return self._with_statute_quota(self._base(config), config)

    def _base(self, config: RetrievalConfig) -> OptionRetriever:
        if config.mode is RetrievalMode.A:
            return VectorOptionRetriever(self._vector_search(), config)
        if config.mode is RetrievalMode.B:
            return HybridOptionRetriever(self._bm25_search(), self._vector_search(), config)
        encoder = self._cross_encoder()  # 모델이 없으면 DB에 연결하기 전에 실패
        hybrid = HybridOptionRetriever(self._bm25_search(), self._vector_search(), config)
        return RerankOptionRetriever(hybrid, encoder, config)

    def _with_statute_quota(
        self, base: OptionRetriever, config: RetrievalConfig
    ) -> OptionRetriever:
        """CR-018: 보기별 상위 `k_opt` 안에 조문 `k_law`개를 보장한다.

        보충 검색은 같은 모드의 **조문 전용** 검색기다(재정렬은 보충에 쓰지 않는다 — 보조 경로이고
        모든 구성에 같은 방식이어야 INV-08이 지켜진다).
        """
        if config.k_law < 1:
            return base
        if config.mode is RetrievalMode.A:
            statutes: OptionRetriever = VectorOptionRetriever(
                self._vector_search(), config, kind=STATUTE_KIND
            )
        else:
            statutes = HybridOptionRetriever(
                self._bm25_search(), self._vector_search(), config, kind=STATUTE_KIND
            )
        return StatuteQuotaRetriever(base, statutes, k_law=config.k_law, k_opt=config.k_opt)

    def _cross_encoder(self) -> BaseCrossEncoder:
        if self._encoder is None:
            if self._cross_encoder_factory is None:
                raise RetrievalFailedError("재정렬 모델이 주어지지 않았습니다(구성 C).")
            self._encoder = self._cross_encoder_factory()
        return self._encoder

    def _vector_search(self) -> VectorSearch:
        if self._vector is None:
            self._vector = VectorSearch(
                self._sqlalchemy_url, self._embeddings, self._embedding_dim, self._version()
            )
        return self._vector

    def _bm25_search(self) -> Bm25Search:
        if self._bm25 is None:
            self._bm25 = Bm25Search(self._chunks.list_chunks(self._version()), self._tokenize)
        return self._bm25

    def _version(self) -> str:
        if self._index_version is None:
            raise IndexNotReadyError("검색할 색인 판본이 없습니다.")
        return self._index_version


def build_retrieval_service(
    chunks: ChunkQueryService,
    settings: Settings,
    *,
    index_version: str | None,
    sqlalchemy_url: str,
    embeddings: Embeddings,
    tokenize: Callable[[str], list[str]],
    cross_encoder: Callable[[], BaseCrossEncoder] | None = None,
    rewriter: QueryRewriterPort | None = None,
) -> RetrievalService:
    """진입점(`ask`·`eval run`·Streamlit)이 판본·임베딩·토큰화를 골라 넘긴다.

    `cross_encoder`를 넘기지 않으면 설정의 재정렬 모델(`reranker`, `reranker_device`)을
    구성 C를 처음 쓸 때 한 번 적재한다. `rewriter`가 없으면 C+R은 조립 오류.
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
        ),
        rewriter=rewriter,
    )


def build_rewriter(settings: Settings) -> OpenAIQueryRewriter:
    """§5.2 리라이터(생성과 같은 모델, 시간 제한 `rewrite_s`)."""
    chat = rewrite_chat_model(
        settings.models.generation,
        settings.secrets.require("openai_api_key"),
        settings.timeouts.rewrite_s,
    )
    return OpenAIQueryRewriter(chat, RewritePrompt.load())

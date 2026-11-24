"""TKT-BE-M2-04: 검색 서비스·구성 A·B (AC-06-1, AC-07-1·2). 가짜 검색기·가짜 벡터 검색, DB·API 없음.

실제 PGVector·OpenAI 연동은 `check smoke`와 DB 통합 시험이 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from lawqa.corpus.domain.models import Chunk, DocumentKind, SourceLocation
from lawqa.retrieval.application.retrieval_service import RetrievalService
from lawqa.retrieval.domain.errors import RetrievalFailedError
from lawqa.retrieval.domain.models import (
    Candidate,
    ExamItem,
    OptionQuery,
    RetrievalConfig,
    RetrievalMode,
)
from lawqa.retrieval.infrastructure import RetrieverFactory, retrieval_config
from lawqa.retrieval.infrastructure.retrievers import (
    Bm25Search,
    HybridOptionRetriever,
    Scored,
    VectorOptionRetriever,
    chunk_document,
)
from lawqa.shared.settings import load_settings

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
ITEM = ExamItem(stem="지문", options=("하나", "둘", "셋", "넷", "다섯"))
PARAMS = {"n_vec": 3, "n_bm25": 3, "n_fuse": 4, "k_opt": 2, "rrf_c": 60, "weights": (0.5, 0.5)}


def _config(name: str = "B", mode: RetrievalMode = RetrievalMode.B, **over) -> RetrievalConfig:
    return RetrievalConfig(name=name, mode=mode, use_rewrite=name == "C+R", **{**PARAMS, **over})  # type: ignore[arg-type]


def _chunk(doc: str, text: str) -> Chunk:
    return Chunk(
        index_version="v1",
        chunk_id=f"{doc}#ARTICLE#1",
        doc_id=doc,
        kind=DocumentKind.STATUTE_ARTICLE,
        section="ARTICLE",
        seq=1,
        location=SourceLocation(f"민법 {doc}"),
        text=text,
        referenced_articles=None,
        bm25_tokens=tuple(text.split()),
    )


CHUNKS = [
    _chunk("c1", "계약 해제 원상회복"),
    _chunk("c2", "소멸시효 중단 사유"),
    _chunk("c3", "계약 해제 손해배상"),
    _chunk("c4", "점유 취득시효"),
    _chunk("c5", "상속 한정승인"),
    _chunk("c6", "유치권 성립 요건"),
    _chunk("c7", "보증 채무 범위"),
    _chunk("c8", "부당이득 반환 범위"),
]


class _ListRetriever(BaseRetriever):
    docs: list[Document]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return self.docs


class FakeVectorSearch:
    """정해진 순서의 벡터 결과(점수 = 코사인 유사도 흉내)."""

    def __init__(self, chunk_ids: list[str], fail: bool = False) -> None:
        by_id = {c.doc_id: chunk_document(c) for c in CHUNKS}
        self.docs = [by_id[i] for i in chunk_ids]
        self.fail = fail
        self.queries: list[str] = []

    def search(self, query: str, k: int) -> list[Scored]:
        self.queries.append(query)
        if self.fail:
            raise ConnectionError("db down")
        return [Scored(d, r, 0.9 - r / 10) for r, d in enumerate(self.docs[:k], start=1)]

    def as_retriever(self, k: int) -> BaseRetriever:
        return _ListRetriever(docs=self.docs[:k])


class RecordingRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[Candidate]:
        self.queries.append(query)
        n = len(self.queries)
        return [Candidate(f"d{n}#ARTICLE#1", f"d{n}", "loc", "t", final_rank=1)]


# ── RetrievalService ──
def test_service_searches_each_option_with_its_query():
    fake = RecordingRetriever()
    result = RetrievalService(retriever_for=lambda c: fake).retrieve(ITEM, _config())

    assert result.config_name == "B"
    assert fake.queries == [f"지문\n{o}" for o in ITEM.options]
    assert [o.query.option_no for o in result.options] == [1, 2, 3, 4, 5]
    assert result.options[2].candidates[0].chunk_id == "d3#ARTICLE#1"


def test_service_uses_given_queries_effective_text():
    fake = RecordingRetriever()
    queries = [OptionQuery(n, f"원{n}", rewritten=f"법률{n}") for n in range(1, 6)]
    RetrievalService(retriever_for=lambda c: fake).retrieve(ITEM, _config(), queries)
    assert fake.queries == [f"법률{n}" for n in range(1, 6)]


def test_service_propagates_retrieval_failure():
    class Failing:
        def retrieve(self, query: str) -> list[Candidate]:
            raise RetrievalFailedError("down")

    with pytest.raises(RetrievalFailedError):
        RetrievalService(retriever_for=lambda c: Failing()).retrieve(ITEM, _config())


# ── 구성 A ──
def test_config_a_records_vector_rank_and_score():
    retriever = VectorOptionRetriever(
        FakeVectorSearch(["c3", "c1", "c2"]), _config("A", RetrievalMode.A, n_vec=2)
    )
    cands = retriever.retrieve("계약 해제")

    assert [c.chunk_id for c in cands] == ["c3#ARTICLE#1", "c1#ARTICLE#1"]
    assert [(c.vector_rank, c.final_rank) for c in cands] == [(1, 1), (2, 2)]
    assert cands[0].vector_score == pytest.approx(0.8)
    assert cands[0].bm25_rank is None and cands[0].location == "민법 c3"


def test_vector_failure_becomes_retrieval_failed():
    retriever = VectorOptionRetriever(
        FakeVectorSearch([], fail=True), _config("A", RetrievalMode.A)
    )
    with pytest.raises(RetrievalFailedError):
        retriever.retrieve("q")


# ── 구성 B ──
def test_bm25_returns_only_matching_chunks_with_scores():
    hits = Bm25Search(CHUNKS, str.split).search("계약 해제", k=3)
    assert {h.doc.metadata["chunk_id"] for h in hits} == {"c1#ARTICLE#1", "c3#ARTICLE#1"}
    assert [h.rank for h in hits] == [1, 2]
    assert all(h.score > 0 for h in hits)


def test_config_b_fuses_with_rrf_and_dedupes_by_chunk_id():
    vector = FakeVectorSearch(["c2", "c3", "c4"])
    retriever = HybridOptionRetriever(Bm25Search(CHUNKS, str.split), vector, _config())
    cands = retriever.retrieve("계약 해제")
    by_id = {c.chunk_id: c for c in cands}

    # AC-07-2: c3는 두 검색기에 모두 있지만 한 번만
    assert len(cands) == len(by_id) == 4
    # 가중 RRF: c3 = 0.5/(60+bm25순위) + 0.5/(60+2) 가 가장 큼
    assert cands[0].chunk_id == "c3#ARTICLE#1"
    c3 = by_id["c3#ARTICLE#1"]
    assert c3.bm25_rank is not None and c3.vector_rank == 2
    # AC-07-1: 개별 순위·점수와 결합 순위가 함께 기록
    assert by_id["c2#ARTICLE#1"].bm25_rank is None and by_id["c2#ARTICLE#1"].vector_rank == 1
    assert [c.fused_rank for c in cands] == [1, 2, 3, 4] == [c.final_rank for c in cands]
    assert len(vector.queries) == 1  # 질의 임베딩은 한 번


def test_config_b_respects_n_fuse():
    retriever = HybridOptionRetriever(
        Bm25Search(CHUNKS, str.split), FakeVectorSearch(["c2", "c3", "c4"]), _config(n_fuse=2)
    )
    assert len(retriever.retrieve("계약 해제")) == 2


def test_rrf_is_not_score_sum():
    """점수가 아니라 순위만 쓴다: BM25 점수 크기와 상관없이 각 목록의 1위는 RRF 점수가 같다."""
    retriever = HybridOptionRetriever(
        Bm25Search(CHUNKS, str.split), FakeVectorSearch(["c4"]), _config()
    )
    cands = retriever.retrieve("소멸시효 중단 사유 사유 사유")
    # c2(BM25 1위)와 c4(벡터 1위)는 같은 가중치·같은 순위라 RRF 점수가 같다
    assert {c.chunk_id for c in cands[:2]} == {"c2#ARTICLE#1", "c4#ARTICLE#1"}


# ── 조립 ──
def test_factory_config_c_needs_cross_encoder():
    class Chunks:
        def list_chunks(self, index_version: str) -> list[Chunk]:
            return CHUNKS

    factory = RetrieverFactory(
        chunks=Chunks(),  # type: ignore[arg-type]
        index_version="v1",
        sqlalchemy_url="postgresql+psycopg://unused",
        embeddings=None,  # type: ignore[arg-type]
        embedding_dim=1536,
        tokenize=str.split,
    )
    with pytest.raises(RetrievalFailedError):
        factory(_config("C", RetrievalMode.C))


@pytest.mark.parametrize(("name", "mode"), [("A", "A"), ("B", "B"), ("C", "C"), ("C+R", "C")])
def test_retrieval_config_from_settings(name, mode):
    config = retrieval_config(load_settings(name, config_dir=CONFIG_DIR, environ={}))
    assert config.name == name and config.mode.value == mode
    assert config.use_rewrite == (name == "C+R")


def test_retrieval_config_rejects_base():
    with pytest.raises(ValueError):
        retrieval_config(load_settings("base", config_dir=CONFIG_DIR, environ={}))

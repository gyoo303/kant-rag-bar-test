"""TKT-BE-M3-01: 구성 C 재정렬 순서 (AC-08-1·2). 가짜 CrossEncoder 점수, GPU·모델 없음."""

from __future__ import annotations

import pytest
from langchain_community.cross_encoders import BaseCrossEncoder

from lawqa.retrieval.domain.errors import RerankerFailedError
from lawqa.retrieval.domain.models import Candidate, RetrievalConfig, RetrievalMode
from lawqa.retrieval.infrastructure.reranker import (
    RecordingCrossEncoder,
    RerankOptionRetriever,
    resolve_device,
)

CONFIG = RetrievalConfig(
    name="C",
    mode=RetrievalMode.C,
    use_rewrite=False,
    n_vec=20,
    n_bm25=20,
    n_fuse=5,
    k_opt=3,
    rrf_c=60,
    weights=(0.5, 0.5),
)


class FakeHybrid:
    """구성 B 결과 흉내: 결합 순위 1..n."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def retrieve(self, query: str) -> list[Candidate]:
        return [
            Candidate(
                chunk_id=f"d{i}#HOLDING#1",
                doc_id=f"d{i}",
                location=f"loc{i}",
                text=t,
                bm25_rank=i,
                fused_rank=i,
                final_rank=i,
            )
            for i, t in enumerate(self.texts, start=1)
        ]


class TableEncoder(BaseCrossEncoder):
    """문서 본문 → 정해진 점수."""

    def __init__(self, table: dict[str, float], fail: bool = False) -> None:
        self.table = table
        self.fail = fail
        self.calls = 0

    def score(self, text_pairs: list[tuple[str, str]]) -> list[float]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("CUDA out of memory")
        return [self.table[doc] for _, doc in text_pairs]


SCORES = {"a": 0.1, "b": 0.9, "c": 0.5, "d": 0.95, "e": -2.0}


def test_output_order_follows_rerank_scores_not_fused_order():
    encoder = TableEncoder(SCORES)
    cands = RerankOptionRetriever(FakeHybrid(list("abcde")), encoder, CONFIG).retrieve("q")

    # AC-08-2: 재정렬 점수 내림차순(d 0.95, b 0.9, c 0.5), k_opt=3개
    assert [c.text for c in cands] == ["d", "b", "c"]
    assert [c.rerank_score for c in cands] == [0.95, 0.9, 0.5]
    # AC-08-1: 재정렬 전 순위(fused_rank)와 후 순위(final_rank)가 함께 남음
    assert [(c.fused_rank, c.final_rank) for c in cands] == [(4, 1), (2, 2), (3, 3)]
    assert cands[0].bm25_rank == 4  # B 단계 기록도 유지
    assert encoder.calls == 1  # 점수 계산은 한 번


def test_ties_keep_fused_order():
    encoder = TableEncoder({"a": 0.5, "b": 0.5, "c": 0.5})
    cands = RerankOptionRetriever(FakeHybrid(list("abc")), encoder, CONFIG).retrieve("q")
    assert [c.text for c in cands] == ["a", "b", "c"]


def test_fewer_candidates_than_k_opt():
    cands = RerankOptionRetriever(FakeHybrid(["a"]), TableEncoder(SCORES), CONFIG).retrieve("q")
    assert [(c.text, c.final_rank) for c in cands] == [("a", 1)]


def test_empty_hybrid_result_skips_model():
    encoder = TableEncoder(SCORES)
    assert RerankOptionRetriever(FakeHybrid([]), encoder, CONFIG).retrieve("q") == []
    assert encoder.calls == 0


def test_model_failure_becomes_retrieval_failed():
    retriever = RerankOptionRetriever(
        FakeHybrid(list("ab")), TableEncoder(SCORES, fail=True), CONFIG
    )
    with pytest.raises(RerankerFailedError):
        retriever.retrieve("q")


def test_recording_encoder_returns_plain_floats():
    class ArrayLike(BaseCrossEncoder):
        def score(self, text_pairs):
            return map(lambda x: x, [1, 2])  # HuggingFaceCrossEncoder처럼 map을 돌려줄 수 있음

    rec = RecordingCrossEncoder(ArrayLike())
    assert rec.score([("q", "a"), ("q", "b")]) == [1.0, 2.0]
    assert rec.last_scores == [1.0, 2.0]


def test_resolve_device_keeps_cpu():
    assert resolve_device("cpu") == "cpu"

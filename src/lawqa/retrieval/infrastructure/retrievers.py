"""검색 구성 A·B (ADR-009, ADR-011, 05-structure-conventions S-01·S-02).

- A: PGVector 벡터 검색 상위 `n_vec`.
- B: BM25(Kiwi 토큰) 상위 `n_bm25` + 벡터 상위 `n_vec` → `EnsembleRetriever`의 가중 RRF
  (`weights`, `c=rrf_c`, `id_key="chunk_id"`로 같은 청크는 한 번) → 상위 `n_fuse`.
  점수 단순 합산이 아니다(REQ-050·052).
- 기록용으로 BM25·벡터 목록의 순위·점수를 따로 남긴다(AC-07-1). 두 목록은 한 번씩만 구하고,
  결합은 같은 목록에 `EnsembleRetriever.weighted_reciprocal_rank`를 적용한다
  (질의 임베딩을 두 번 부르지 않기 위해).
- 외부 오류는 `RetrievalFailedError`로 바꿔 던진다(ADR-004, answering이 결과로 변환).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_postgres import PGVector
from rank_bm25 import BM25Okapi

from lawqa.corpus.domain.models import Chunk, collection_name_for
from lawqa.retrieval.domain.errors import RetrievalFailedError
from lawqa.retrieval.domain.models import Candidate, RetrievalConfig
from lawqa.retrieval.domain.ports import OptionRetriever

ID_KEY = "chunk_id"


@dataclass(frozen=True, slots=True)
class Scored:
    """한 검색기의 결과 하나(1부터 순위, 점수는 높을수록 관련)."""

    doc: Document
    rank: int
    score: float


def chunk_document(chunk: Chunk) -> Document:
    """BM25 색인용 문서. 메타데이터는 벡터 표(`chunk_metadata`)와 같은 키를 쓴다."""
    return Document(
        page_content=chunk.text,
        metadata={
            ID_KEY: chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "kind": chunk.kind.value,  # CR-018: 조문 몫 보장에 쓴다
            "location": chunk.location.text,
            "index_version": chunk.index_version,
        },
    )


class Bm25Search:
    """`BM25Retriever`(LangChain)를 만들고, 기록용 점수까지 함께 돌려준다(S-02).

    색인은 청크 표에 저장된 `bm25_tokens`로 만든다(기동 때 4만여 청크를 다시 형태소 분석하지
    않음). 질의는 같은 Kiwi 토큰화(`tokenize`)를 쓴다.
    """

    def __init__(self, chunks: Sequence[Chunk], tokenize: Callable[[str], list[str]]) -> None:
        if not chunks:
            raise RetrievalFailedError("BM25 색인을 만들 청크가 없습니다.")
        self.retriever = BM25Retriever(
            vectorizer=BM25Okapi([list(c.bm25_tokens) for c in chunks]),
            docs=[chunk_document(c) for c in chunks],
            preprocess_func=tokenize,
        )

    def search(self, query: str, k: int, kind: str | None = None) -> list[Scored]:
        """점수 > 0인(질의 낱말이 하나라도 겹치는) 상위 k개. `kind`를 주면 그 종류만(CR-018)."""
        tokens = self.retriever.preprocess_func(query)
        scores = self.retriever.vectorizer.get_scores(tokens)
        allowed = range(len(scores))
        if kind is not None:
            allowed = [i for i in allowed if self.retriever.docs[i].metadata.get("kind") == kind]
        order = sorted(allowed, key=lambda i: (-scores[i], i))[:k]
        hits = [(i, float(scores[i])) for i in order if scores[i] > 0]
        return [
            Scored(self.retriever.docs[i], rank, score)
            for rank, (i, score) in enumerate(hits, start=1)
        ]


class VectorSearch:
    """PGVector 검색(코사인). 점수는 `1 - 코사인 거리`(= 코사인 유사도)로 기록한다."""

    def __init__(
        self, sqlalchemy_url: str, embeddings: Embeddings, embedding_dim: int, index_version: str
    ) -> None:
        self.store = PGVector(
            embeddings=embeddings,
            connection=sqlalchemy_url,
            embedding_length=embedding_dim,
            collection_name=collection_name_for(index_version),
            use_jsonb=True,
            create_extension=False,
        )

    def search(self, query: str, k: int, kind: str | None = None) -> list[Scored]:
        """`kind`를 주면 그 종류의 청크만 본다(PGVector 메타데이터 필터, CR-018)."""
        kw = {"filter": {"kind": {"$eq": kind}}} if kind is not None else {}
        pairs = self.store.similarity_search_with_score(query, k=k, **kw)
        return [
            Scored(doc, rank, 1.0 - float(distance))
            for rank, (doc, distance) in enumerate(pairs, start=1)
        ]

    def as_retriever(self, k: int) -> BaseRetriever:
        return self.store.as_retriever(search_kwargs={"k": k})


class VectorOptionRetriever:
    """구성 A: 벡터 상위 `n_vec`(`final_rank` = 벡터 순위)."""

    def __init__(
        self, vector: VectorSearch, config: RetrievalConfig, *, kind: str | None = None
    ) -> None:
        self._vector = vector
        self._n_vec = config.n_vec
        self._kind = kind  # CR-018: 조문 보충 검색용

    def retrieve(self, query: str) -> list[Candidate]:
        try:
            hits = self._vector.search(query, self._n_vec, self._kind)
        except Exception as exc:  # 외부(OpenAI·DB) 오류 → 도메인 예외(ADR-004)
            raise RetrievalFailedError(f"벡터 검색 실패: {type(exc).__name__}: {exc}") from exc
        return [_candidate(h.doc, vector=h, final_rank=h.rank) for h in hits]


class HybridOptionRetriever:
    """구성 B: BM25 + 벡터 → 가중 RRF(`EnsembleRetriever`) 상위 `n_fuse`."""

    def __init__(
        self,
        bm25: Bm25Search,
        vector: VectorSearch,
        config: RetrievalConfig,
        *,
        kind: str | None = None,
    ) -> None:
        self._bm25 = bm25
        self._vector = vector
        self._config = config
        self._kind = kind  # CR-018: 조문 보충 검색용
        self.ensemble = EnsembleRetriever(
            retrievers=[
                bm25.retriever,
                vector.as_retriever(config.n_vec),
            ],
            weights=list(config.weights),
            c=config.rrf_c,
            id_key=ID_KEY,
        )

    def retrieve(self, query: str) -> list[Candidate]:
        try:
            bm25_hits = self._bm25.search(query, self._config.n_bm25, self._kind)
            vector_hits = self._vector.search(query, self._config.n_vec, self._kind)
        except Exception as exc:  # 외부(OpenAI·DB) 오류 → 도메인 예외(ADR-004)
            raise RetrievalFailedError(
                f"하이브리드 검색 실패: {type(exc).__name__}: {exc}"
            ) from exc
        fused = self.ensemble.weighted_reciprocal_rank(
            [[h.doc for h in bm25_hits], [h.doc for h in vector_hits]]
        )[: self._config.n_fuse]
        by_bm25 = {h.doc.metadata[ID_KEY]: h for h in bm25_hits}
        by_vector = {h.doc.metadata[ID_KEY]: h for h in vector_hits}
        candidates = []
        for rank, doc in enumerate(fused, start=1):
            chunk_id = doc.metadata[ID_KEY]
            candidates.append(
                _candidate(
                    doc,
                    bm25=by_bm25.get(chunk_id),
                    vector=by_vector.get(chunk_id),
                    fused_rank=rank,
                    final_rank=rank,
                )
            )
        return candidates


def _candidate(
    doc: Document,
    *,
    bm25: Scored | None = None,
    vector: Scored | None = None,
    fused_rank: int | None = None,
    final_rank: int,
) -> Candidate:
    meta: dict[str, Any] = doc.metadata
    return Candidate(
        chunk_id=meta[ID_KEY],
        doc_id=meta["doc_id"],
        location=meta["location"],
        text=doc.page_content,
        bm25_rank=bm25.rank if bm25 else None,
        bm25_score=bm25.score if bm25 else None,
        vector_rank=vector.rank if vector else None,
        vector_score=vector.score if vector else None,
        fused_rank=fused_rank,
        final_rank=final_rank,
    )


STATUTE_KIND = "STATUTE_ARTICLE"


def is_statute(candidate: Candidate) -> bool:
    """조문 청크인가. `doc_id`가 `law:<법령명>:<조>-<가지>` 형식이다(ADR-015)."""
    return candidate.doc_id.startswith("law:")


class StatuteQuotaRetriever:
    """상위 `k_opt` 안에 조문을 최소 `k_law`개 보장한다 (CR-018).

    말뭉치가 판례 89%라 조문이 점수 경쟁에서 묻힌다. 실측(2026-11-24 재측정)에서 틀린 10문항의
    조문 비율이 3.8%였고 7문항은 조문이 0개였는데, 필요한 조문은 색인에 있었다 — 순위 문제다.

    모자라면 ① 이미 받은 목록의 더 아래쪽 조문을 끌어올리고 ② 그래도 모자라면 같은 질의로
    **조문만** 검색해 채운다. 채우는 자리는 상위 `k_opt` 안에서 가장 순위가 낮은 판례를 밀어낸다.
    모든 구성(A·B·C·C+R)을 같은 방식으로 감싸 비교 공정성을 지킨다(INV-08).
    """

    def __init__(
        self, inner: OptionRetriever, statutes: OptionRetriever, *, k_law: int, k_opt: int
    ) -> None:
        self._inner = inner
        self._statutes = statutes
        self._k_law = k_law
        self._k_opt = k_opt

    def retrieve(self, query: str) -> list[Candidate]:
        base = self._inner.retrieve(query)
        if self._k_law < 1:
            return base
        head, tail = base[: self._k_opt], base[self._k_opt :]
        need = self._k_law - sum(1 for c in head if is_statute(c))
        if need < 1:
            return base

        seen = {c.chunk_id for c in base}
        extra = [c for c in tail if is_statute(c)][:need]
        if len(extra) < need:
            for c in self._statutes.retrieve(query):
                if len(extra) == need:
                    break
                if c.chunk_id not in seen:
                    extra.append(c)
                    seen.add(c.chunk_id)
        if not extra:
            return base

        promoted = [c for c in extra]
        keep = [c for c in head if c.chunk_id not in {c.chunk_id for c in promoted}]
        # 상위 k_opt 안에서 순위가 낮은 판례부터 밀어낸다(조문은 남긴다)
        drop = len(keep) + len(promoted) - self._k_opt
        for _ in range(max(drop, 0)):
            victim = next((c for c in reversed(keep) if not is_statute(c)), None)
            if victim is None:
                break
            keep.remove(victim)
        rest = [c for c in base if c.chunk_id not in {c.chunk_id for c in keep + promoted}]
        return _renumber(keep + promoted + rest)


def _renumber(candidates: list[Candidate]) -> list[Candidate]:
    """합친 뒤 `final_rank`를 1부터 다시 매긴다(기록·재정렬 순서의 기준)."""
    return [replace(c, final_rank=rank) for rank, c in enumerate(candidates, start=1)]

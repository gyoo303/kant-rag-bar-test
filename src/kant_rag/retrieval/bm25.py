"""BM25 검색 (rank_bm25). LangChain BM25Retriever 는 점수를 돌려주지 않아 직접 사용합니다."""

from __future__ import annotations

import pickle
from pathlib import Path

from kant_rag.retrieval.tokenizer import get_tokenizer
from kant_rag.schemas import Chunk, RetrievedChunk


class BM25Index:
    def __init__(self, chunks: list[Chunk], tokenizer: str, bm25=None):
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self.tokenizer_name = tokenizer
        self._tok = get_tokenizer(tokenizer)
        self.bm25 = bm25 or BM25Okapi([self._tok(c.text) for c in chunks])

    @classmethod
    def build(cls, chunks: list[Chunk], tokenizer: str = "simple") -> BM25Index:
        return cls(chunks, tokenizer)

    def save(self, path: Path) -> None:
        with path.open("wb") as f:
            pickle.dump({"chunks": self.chunks, "tokenizer": self.tokenizer_name, "bm25": self.bm25}, f)

    @classmethod
    def load(cls, path: Path) -> BM25Index:
        with path.open("rb") as f:
            d = pickle.load(f)  # 로컬에서 직접 생성한 파일만 로드합니다
        return cls(d["chunks"], d["tokenizer"], d["bm25"])

    def search(self, query: str, k: int) -> list[RetrievedChunk]:
        scores = self.bm25.get_scores(self._tok(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in order[:k]:
            if scores[i] <= 0:  # 겹치는 토큰이 없는 문서는 후보에서 제외
                break
            out.append(RetrievedChunk(chunk=self.chunks[i], score=float(scores[i]),
                                      rank=len(out) + 1, source="bm25",
                                      trace={"bm25_score": float(scores[i]), "bm25_rank": len(out) + 1}))
        return out

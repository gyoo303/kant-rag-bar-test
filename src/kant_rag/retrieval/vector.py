"""벡터 검색 (LangChain FAISS + HuggingFace 임베딩, 코사인 유사도)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from kant_rag.schemas import Chunk, RetrievedChunk


@lru_cache
def get_embeddings(model_name: str):
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=model_name, show_progress=True,
                                 encode_kwargs={"normalize_embeddings": True, "batch_size": 32})


class VectorIndex:
    def __init__(self, store, chunks_by_id: dict[str, Chunk]):
        self.store = store
        self.chunks_by_id = chunks_by_id

    @classmethod
    def build(cls, chunks: list[Chunk], embedding_model: str) -> VectorIndex:
        from langchain_community.vectorstores import FAISS
        from langchain_community.vectorstores.utils import DistanceStrategy

        store = FAISS.from_texts(
            texts=[c.text for c in chunks],
            embedding=get_embeddings(embedding_model),
            metadatas=[{"chunk_id": c.chunk_id} for c in chunks],
            ids=[c.chunk_id for c in chunks],
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,  # 정규화 벡터 → 코사인
        )
        return cls(store, {c.chunk_id: c for c in chunks})

    def save(self, path: Path) -> None:
        self.store.save_local(str(path))

    @classmethod
    def load(cls, path: Path, embedding_model: str, chunks: list[Chunk]) -> VectorIndex:
        from langchain_community.vectorstores import FAISS

        store = FAISS.load_local(
            str(path), get_embeddings(embedding_model), allow_dangerous_deserialization=True
        )
        return cls(store, {c.chunk_id: c for c in chunks})

    def search(self, query: str, k: int) -> list[RetrievedChunk]:
        hits = self.store.similarity_search_with_score(query, k=k)
        out = []
        for rank, (doc, score) in enumerate(hits, start=1):
            chunk = self.chunks_by_id[doc.metadata["chunk_id"]]
            out.append(RetrievedChunk(chunk=chunk, score=float(score), rank=rank, source="vector",
                                      trace={"vector_score": float(score), "vector_rank": rank}))
        return out

"""벡터 검색 (LangChain FAISS + 임베딩, 코사인 유사도).

임베딩 백엔드는 모델 이름으로 고릅니다 (EMBEDDING_MODEL):
- `text-embedding-3-small` 등 `text-embedding-*` 또는 `openai:<모델>` → OpenAI 임베딩 API (GPU 불필요, 교안 표준)
- 그 외(예: `BAAI/bge-m3`) → 로컬 HuggingFace 모델 (GPU 권장)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from kant_rag.schemas import Chunk, RetrievedChunk


def is_openai_embedding(model_name: str) -> bool:
    return model_name.startswith(("text-embedding-", "openai:"))


@lru_cache
def get_embeddings(model_name: str, max_tokens: int = 1024, batch_size: int = 8, fp16: bool = True):
    if is_openai_embedding(model_name):
        from langchain_openai import OpenAIEmbeddings

        name = model_name.removeprefix("openai:")
        print(f"[embedding] OpenAI {name} (API 호출, GPU 불필요)", flush=True)
        # text-embedding-3 계열은 길이 1로 정규화된 벡터 → 내적 = 코사인
        return OpenAIEmbeddings(model=name, chunk_size=256, show_progress_bar=True, max_retries=6)
    import torch
    from langchain_huggingface import HuggingFaceEmbeddings

    cuda = torch.cuda.is_available()
    model_kwargs = {"device": "cuda" if cuda else "cpu"}
    if cuda and fp16:
        model_kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
    emb = HuggingFaceEmbeddings(model_name=model_name, show_progress=True, model_kwargs=model_kwargs,
                                encode_kwargs={"normalize_embeddings": True, "batch_size": batch_size})
    emb._client.max_seq_length = max_tokens  # bge-m3 기본 8192 → 8GB GPU 에서 OOM
    print(f"[embedding] {model_name} device={model_kwargs['device']} fp16={cuda and fp16} "
          f"max_tokens={max_tokens} batch={batch_size}", flush=True)
    return emb


def _cfg(emb_cfg) -> tuple:
    return (emb_cfg.max_tokens, emb_cfg.batch_size, emb_cfg.fp16) if emb_cfg else ()


class VectorIndex:
    def __init__(self, store, chunks_by_id: dict[str, Chunk]):
        self.store = store
        self.chunks_by_id = chunks_by_id

    @classmethod
    def build(cls, chunks: list[Chunk], embedding_model: str, emb_cfg=None) -> VectorIndex:
        from langchain_community.vectorstores import FAISS
        from langchain_community.vectorstores.utils import DistanceStrategy

        store = FAISS.from_texts(
            texts=[c.text for c in chunks],
            embedding=get_embeddings(embedding_model, *_cfg(emb_cfg)),
            metadatas=[{"chunk_id": c.chunk_id} for c in chunks],
            ids=[c.chunk_id for c in chunks],
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,  # 정규화 벡터 → 코사인
        )
        return cls(store, {c.chunk_id: c for c in chunks})

    def save(self, path: Path) -> None:
        self.store.save_local(str(path))

    @classmethod
    def load(cls, path: Path, embedding_model: str, chunks: list[Chunk], emb_cfg=None) -> VectorIndex:
        from langchain_community.vectorstores import FAISS

        store = FAISS.load_local(
            str(path), get_embeddings(embedding_model, *_cfg(emb_cfg)), allow_dangerous_deserialization=True
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

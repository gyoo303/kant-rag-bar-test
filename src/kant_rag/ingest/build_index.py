"""색인 재생성: manifest → 정제 → 청킹 → chunks.jsonl + BM25 + 벡터 색인."""

from __future__ import annotations

import json
import time

from kant_rag.config import Settings
from kant_rag.ingest.chunker import chunk_text
from kant_rag.ingest.loader import clean_text, load_pages, read_manifest
from kant_rag.schemas import Chunk


def build_chunks(settings: Settings) -> list[Chunk]:
    docs = read_manifest(settings.resolve(settings.paths.manifest))
    raw_dir = settings.resolve(settings.paths.raw_dir)
    chunks: list[Chunk] = []
    for meta in docs:
        path = raw_dir / meta.path
        if not path.exists():
            raise FileNotFoundError(f"{meta.doc_id}: 원문 파일 없음 → {path}")
        for p_idx, page in enumerate(load_pages(path)):
            chunks.extend(
                chunk_text(
                    clean_text(page.text),
                    meta,
                    settings.chunking.chunk_size,
                    settings.chunking.chunk_overlap,
                    page=page.page,
                    section_offset=0 if page.page is None else p_idx * 100,
                )
            )
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("청크 ID 충돌")
    return chunks


def build_index(settings: Settings) -> dict:
    from kant_rag.retrieval.bm25 import BM25Index
    from kant_rag.retrieval.vector import VectorIndex

    t0 = time.perf_counter()
    index_dir = settings.resolve(settings.paths.index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)

    chunks = build_chunks(settings)
    with (index_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")

    BM25Index.build(chunks, settings.retrieval.bm25_tokenizer).save(index_dir / "bm25.pkl")
    VectorIndex.build(chunks, settings.models.embedding_model).save(index_dir / "faiss")

    info = {
        "versions": settings.versions.model_dump(),
        "chunking": settings.chunking.model_dump(),
        "embedding_model": settings.models.embedding_model,
        "bm25_tokenizer": settings.retrieval.bm25_tokenizer,
        "n_docs": len({c.doc_id for c in chunks}),
        "n_chunks": len(chunks),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    (index_dir / "index_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def load_chunks(settings: Settings) -> list[Chunk]:
    path = settings.resolve(settings.paths.index_dir) / "chunks.jsonl"
    with path.open(encoding="utf-8") as f:
        return [Chunk.model_validate_json(line) for line in f if line.strip()]

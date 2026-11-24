"""색인 재생성: manifest → 정제 → 청킹 → chunks.jsonl + BM25 + 벡터 색인."""

from __future__ import annotations

import json
import time

from kant_rag.config import Settings
from kant_rag.ingest.chunker import chunk_text
from kant_rag.ingest.loader import clean_text, load_pages, read_manifest
from kant_rag.ingest.statute import chunk_statute
from kant_rag.schemas import Chunk


def build_chunks(settings: Settings) -> list[Chunk]:
    docs = read_manifest(settings.resolve(settings.paths.manifest))
    raw_dir = settings.resolve(settings.paths.raw_dir)
    chunks: list[Chunk] = []
    missing: list[str] = []
    for meta in docs:
        path = raw_dir / meta.path
        if not path.exists():
            # 아직 수집하지 않은 문서(예: kant-rag fetch-laws 미실행)는 건너뛰고 index_info 에 기록
            missing.append(meta.doc_id)
            print(f"[warn] {meta.doc_id}: 원문 파일 없음 → {path} (건너뜀)")
            continue
        if meta.doc_type == "cases":
            from kant_rag.ingest.cases import chunk_cases

            chunks.extend(chunk_cases(path, meta, date_to=settings.corpus.case_date_to))
            continue
        if meta.doc_type == "statute":
            text = "\n".join(clean_text(p.text) for p in load_pages(path))
            chunks.extend(chunk_statute(text, meta, settings.chunking.chunk_size))
            continue
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
    build_chunks.missing = missing  # type: ignore[attr-defined]
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

    by_type: dict[str, int] = {}
    for c in chunks:
        t = c.metadata.get("doc_type", "general")
        by_type[t] = by_type.get(t, 0) + 1
    long_n = sum(len(c.text) > 1500 for c in chunks)
    print(f"[1/3] 청크 {len(chunks)}개 생성 {by_type} · 최장 {max((len(c.text) for c in chunks), default=0)}자 · "
          f"1500자 초과 {long_n}개(임베딩 시 max_tokens 에서 잘릴 수 있음)", flush=True)
    BM25Index.build(chunks, settings.retrieval.bm25_tokenizer).save(index_dir / "bm25.pkl")
    print("[2/3] BM25 색인 완료", flush=True)
    print(f"[3/3] 벡터 임베딩 시작 ({settings.models.embedding_model}) — 진행률이 표시됩니다", flush=True)
    VectorIndex.build(chunks, settings.models.embedding_model, settings.embedding).save(index_dir / "faiss")
    print("벡터 색인 완료", flush=True)

    info = {
        "versions": settings.versions.model_dump(),
        "chunking": settings.chunking.model_dump(),
        "embedding_model": settings.models.embedding_model,
        "embedding": settings.embedding.model_dump(),
        "bm25_tokenizer": settings.retrieval.bm25_tokenizer,
        "n_docs": len({c.doc_id for c in chunks}),
        "n_chunks": len(chunks),
        "missing_docs": getattr(build_chunks, "missing", []),
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

"""색인 생성 (교안 2장 인덱싱 파이프라인).

1) 판례·법령 원문 → 청크 → data/index/chunks.jsonl  (BM25·벡터가 같은 청크 집합을 쓰도록 단일 원본)
2) chunks.jsonl → 벡터 저장소
   - pgvector: PGVector(use_jsonb=True) + SQLRecordManager + index()  (교안 2-5, 2-7)
   - memory  : InMemoryVectorStore → data/index/memory_store.json  (교안 1장, Docker 없이)
3) data/index/manifest.json 에 범위·개수·버전 기록 (문서 목록·재현용)
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from civil_rag import config
from civil_rag.ingest.chunking import Chunk, law_to_chunks, prec_to_chunks

CHUNKS_FILE = config.INDEX_DIR / "chunks.jsonl"
MANIFEST_FILE = config.INDEX_DIR / "manifest.json"
MEMORY_STORE_FILE = config.INDEX_DIR / "memory_store.json"

SEARCHABLE_FIELDS = ("사건명", "판시사항", "판결요지", "참조조문")


def _mtime(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def select_prec_files(
    limit: int = 0,
    court: str | None = None,
    keywords: list[str] | None = None,
    ids_file: Path | None = None,
) -> Iterator[tuple[Path, dict]]:
    """색인할 판례 고르기. 조건을 모두 만족하는 파일만."""
    wanted: set[str] | None = None
    if ids_file:
        wanted = {line.strip() for line in ids_file.read_text(encoding="utf-8").splitlines() if line.strip()}
    kws = [k.strip() for k in (keywords or []) if k.strip()]
    count = 0
    for path in sorted(config.PREC_DIR.glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        if wanted is not None and path.stem not in wanted:
            continue
        try:
            prec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if court and (prec.get("법원명") or "") != court:
            continue
        if kws:
            hay = " ".join(str(prec.get(f) or "") for f in SEARCHABLE_FIELDS)
            if not any(k in hay for k in kws):
                continue
        yield path, prec
        count += 1
        if limit and count >= limit:
            return


def build_chunks(
    limit: int = 0,
    court: str | None = None,
    keywords: list[str] | None = None,
    ids_file: Path | None = None,
    laws: list[str] | None = None,
) -> dict:
    """원문 → chunks.jsonl. 반환: manifest dict."""
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    n_prec = n_prec_chunks = n_law_chunks = 0
    law_names: list[str] = []
    tmp = CHUNKS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for path, prec in select_prec_files(limit, court, keywords, ids_file):
            chunks = prec_to_chunks(prec, fetched_at=_mtime(path))
            for c in chunks:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
            n_prec += 1
            n_prec_chunks += len(chunks)
            if n_prec % 1000 == 0:
                print(f"  판례 {n_prec:,}건 · 청크 {n_prec_chunks:,}")
        law_files = sorted(config.LAW_DIR.glob("*.json")) if config.LAW_DIR.exists() else []
        if laws:
            law_files = [p for p in law_files if p.stem.replace("_", " ") in laws or p.stem in laws]
        for path in law_files:
            chunks = law_to_chunks(json.loads(path.read_text(encoding="utf-8")), fetched_at=_mtime(path))
            for c in chunks:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
            n_law_chunks += len(chunks)
            law_names.append(path.stem.replace("_", " "))
    tmp.replace(CHUNKS_FILE)

    manifest = {
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "index_version": config.INDEX_VERSION,
        "collection": config.COLLECTION_NAME,
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
        "filters": {
            "limit": limit,
            "court": court,
            "keywords": keywords or [],
            "ids_file": str(ids_file) if ids_file else None,
            "laws": laws or "all",
        },
        "prec_docs": n_prec,
        "prec_chunks": n_prec_chunks,
        "laws": law_names,
        "law_chunks": n_law_chunks,
        "total_chunks": n_prec_chunks + n_law_chunks,
        "source": "법제처 국가법령정보센터 (open.law.go.kr)",
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"청크 저장: 판례 {n_prec:,}건 → {n_prec_chunks:,}개, 법령 {len(law_names)}개 → {n_law_chunks:,}개 "
          f"→ {CHUNKS_FILE.relative_to(config.ROOT)}")
    return manifest


def load_chunks() -> list[Chunk]:
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(f"{CHUNKS_FILE} 없음. 먼저 `civil-rag ingest` 를 실행하세요.")
    out = []
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(Chunk(**json.loads(line)))
    return out


def _documents(chunks: Iterable[Chunk], every: int = 2000):
    from langchain_core.documents import Document

    for i, c in enumerate(chunks, 1):
        if i % every == 0:
            print(f"  임베딩·색인 {i:,}개 진행")
        yield Document(id=c.chunk_id, page_content=c.text, metadata=c.metadata)


def build_vector_index(backend: str | None = None) -> dict:
    """chunks.jsonl 전체를 벡터 저장소에 반영. 이미 임베딩한 청크는 캐시를 써서 비용 없이 재색인."""
    from civil_rag.models import embeddings

    backend = backend or config.VECTOR_BACKEND
    chunks = load_chunks()
    print(f"벡터 색인({backend}): 청크 {len(chunks):,}개, 모델 {config.EMBEDDING_MODEL}")

    if backend == "memory":
        from langchain_core.vectorstores import InMemoryVectorStore

        store = InMemoryVectorStore(embeddings())
        batch: list = []
        for doc in _documents(chunks):
            batch.append(doc)
            if len(batch) >= 500:
                store.add_documents(batch, ids=[d.id for d in batch])
                batch = []
        if batch:
            store.add_documents(batch, ids=[d.id for d in batch])
        store.dump(str(MEMORY_STORE_FILE))
        result = {"backend": "memory", "num_added": len(chunks), "path": str(MEMORY_STORE_FILE)}
    elif backend == "pgvector":
        from langchain_classic.indexes import SQLRecordManager, index
        from langchain_postgres import PGVector

        store = PGVector(
            embeddings=embeddings(),
            collection_name=config.COLLECTION_NAME,
            connection=config.DATABASE_URL,
            use_jsonb=True,
        )
        record_manager = SQLRecordManager(f"pgvector/{config.COLLECTION_NAME}", db_url=config.DATABASE_URL)
        record_manager.create_schema()
        # 교안 2-7은 incremental. 여기서는 chunks.jsonl 과 색인을 정확히 일치시키려고 full
        # (범위를 줄여 재색인하면 빠진 청크가 벡터 쪽에만 남아 BM25와 비교가 불공정해지는 것을 방지)
        result = index(
            _documents(chunks),
            record_manager,
            store,
            cleanup="full",
            source_id_key="doc_id",
            batch_size=200,
        )
        result = {"backend": "pgvector", **result}
    else:
        raise ValueError(f"알 수 없는 VECTOR_BACKEND: {backend}")

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8")) if MANIFEST_FILE.exists() else {}
    manifest["vector_index"] = {**result, "indexed_at": dt.datetime.now().isoformat(timespec="seconds")}
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"벡터 색인 완료: {result}")
    return result

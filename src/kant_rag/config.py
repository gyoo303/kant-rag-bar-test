"""설정 로딩: configs/*.yaml + 환경변수(.env)."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class Versions(BaseModel):
    docs: str
    index: str
    prompt: str
    eval: str


class Paths(BaseModel):
    manifest: Path
    raw_dir: Path
    index_dir: Path
    results_dir: Path
    cache_db: Path


class Corpus(BaseModel):
    law_date: str = "20260101"
    case_date_from: str = "20110101"
    case_date_to: str = "20251231"
    topic_level: str = "article"
    cases_per_topic: int = 5


class Chunking(BaseModel):
    chunk_size: int = 500
    chunk_overlap: int = 80
    max_chars: int = 1000


class Embedding(BaseModel):
    max_tokens: int = 1024
    batch_size: int = 8
    fp16: bool = True


class Retrieval(BaseModel):
    vector_k: int = 20
    bm25_k: int = 20
    rrf_k: int = 60
    fused_k: int = 20
    final_k: int = 5
    bm25_tokenizer: str = "simple"


class Rerank(BaseModel):
    min_score: float = 0.2


class Generation(BaseModel):
    max_context_chunks: int = 5
    max_context_chars: int = 4000
    max_tokens: int = 1024


class CacheOpt(BaseModel):
    enabled: bool = False
    ttl_seconds: int = 86400


class RewriteOpt(BaseModel):
    enabled: bool = False


class Optimization(BaseModel):
    cache: CacheOpt = CacheOpt()
    rewrite: RewriteOpt = RewriteOpt()


class MCQ(BaseModel):
    per_statement_k: int = 4
    stem_chars_in_query: int = 300
    max_context_chars: int = 16000
    max_tokens: int = 4096


class Models(BaseModel):
    llm_provider: str
    llm_model: str
    embedding_model: str
    reranker_model: str


class Settings(BaseModel):
    versions: Versions
    paths: Paths
    corpus: Corpus = Corpus()
    chunking: Chunking
    embedding: Embedding = Embedding()
    retrieval: Retrieval
    rerank: Rerank
    generation: Generation
    optimization: Optimization
    mcq: MCQ = MCQ()
    models: Models

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else ROOT / p

    def fingerprint(self) -> str:
        """검색·생성 결과에 영향을 주는 설정의 해시 (캐시 키·실행 기록용)."""
        payload = self.model_dump(mode="json", exclude={"paths", "optimization"})
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(ROOT / ".env")


@lru_cache
def get_settings(config_path: str | None = None) -> Settings:
    _load_dotenv()
    path = Path(config_path or os.getenv("KANT_RAG_CONFIG", "configs/default.yaml"))
    if not path.is_absolute():
        path = ROOT / path
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["models"] = {
        "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
        "llm_model": os.getenv("LLM_MODEL", "gpt-6-luna"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        "reranker_model": os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
    }
    return Settings.model_validate(data)

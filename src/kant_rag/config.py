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
    case_kinds: list[str] = ["민사", "가사"]
    case_codes: list[str] = ["다", "다카", "재다", "민상", "민재항", "마", "그", "스", "므", "으", "브", "카", "라", "머"]
    case_courts: list[str] = ["대법원"]


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
    # 판례 선고일 상한 (YYYYMMDD). 과거 시험을 그 시험 시점 법리로 풀 때 사용 — 이후 판례는 검색에서 제외
    case_date_to: str | int | None = None


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
    max_tokens: int = 16000  # 추론형 모델은 추론 토큰도 포함 → 넉넉히 (빈 응답이면 2배로 1회 재시도)
    rewrite_max_tokens: int = 4000
    # ---- 개선안 v3 스위치 (기본값 = v2 동작) ----
    rewrite_queries: int = 1          # A2: 2 이면 진술마다 쟁점·예외 질의 2개 (rewrite 켜져 있을 때)
    sibling_items: bool = False       # A3: 같은 판결 다른 항목 판시사항 동봉
    expand_references: bool = False   # A4: 준용 조문 자동 추가
    max_expansions: int = 8           # A4 준용 조문 추가 상한 (문항 전체)
    max_siblings: int = 6             # A3 같은 판결 다른 항목 추가 상한 (문항 전체)
    prompt_version: str = "v1"        # B: v2 = 사실관계·전 항목·예외 우선·유보 기준
    fusion: str = "none"              # C: fill_unknown = 유보 진술만 closed-book 판단으로 채움
    fusion_weight: float = 0.5        # C: 채운 판단의 확신도 배율
    # ---- 개선안 v4 스위치 (기본값 = v3 이전 동작, 프리셋 d 에서 켬) ----
    answer_fallback: bool = False     # 판단 조합이 어느 보기와도 안 맞아 전 보기 0점이면 확신도 상한으로 재계산
    answer_fallback_cap: float = 0.95
    rewrite_version: str = "v2"       # v3 = 쟁점·예외 + 사례 속 당사자 지위 질의 (rewrite_queries 3 까지)
    rewrite_stem_chars: int = 300     # 리라이트에 보여 줄 발문 길이 (사례형은 당사자 관계가 뒤쪽에 있음)
    case_meta: bool = False           # 근거 머리에 판례 선고일·전원합의체 여부 표시
    original_query: bool = False      # 리라이트 질의에 진술 원문(발문 제외) 질의도 더해 검색 (검색 안정성)
    tie_rejudge: bool = False         # 최고점 보기가 동점이면 동점을 만든 진술만 다시 판단 (LLM 1회)
    fusion_min_conf: float = 0.0      # C: 지식 판단의 원 확신도가 이 값 미만이면 채우지 않음 (0 = 제한 없음)
    statute_parts: bool = False       # 항 단위로 나뉜 긴 조문의 다른 조각을 함께 제공 (본문·단서 분리 방지)
    max_statute_parts: int = 6


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

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
    # 법령 스냅숏 (YYYYMMDD): 설정하면 법령을 data/raw/statutes@<날짜>/ 에서 읽고 색인을 index@<날짜>/ 에 둔다.
    # 과거 시험을 그 시험 시점 법령으로 풀 때 (fetch-laws → build-index → eval 에 같은 값을 준다)
    statute_snapshot: str | int | None = None


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
    # ---- v5 스위치 (레드팀 공략안 + 구조 분석, 프리셋 v5 에서 켬) ----
    asof_from_stem: bool = False      # 발문의 "YYYY. M. D. 당시/현재/기준" → 그 날짜 이후 판례를 검색에서 제외
    out_of_corpus_warn: bool = False  # 진술·발문의 법령 중 색인에 없는 것을 판단 입력에 경고로 표시
    cross_ref_queries: bool = False   # 다른 진술을 전제로 하는 진술은 그 진술 내용을 검색 질의에 더함
    quote_check: bool = False         # 판단의 인용 문장(quote)이 인용 청크에 실제 있는지 대조
    quote_penalty: float = 1.0        # 대조 실패 판단의 확신도 배율 (1.0 = 기록만)
    calibration: str | None = None    # 확신도 보정표 경로 (kant-rag calibrate 로 생성). 있으면 보기 점수에 보정 확률 사용
    rejudge_ratio: float = 1.0        # 동점 재판단 범위: 2등 점수가 1등 × 이 값 이상이면 재판단 (1.0 = 완전 동점만)
    asof_default: str | None = None   # 발문에 기준 시점이 없을 때 쓸 시험 기준일 YYYYMMDD (과거 시험 재현용)
    hide_future: bool = False         # 기준 시점 뒤 판례를 근거 표시(변경 관계)에서도 숨김 (과거 시험 검증용)
    # ---- v6 스위치 (개선안 v6, 프리셋 v6 에서 켬) ----
    rewrite_key_normalize: bool = False  # 0-1 리라이트 출력 키 정규화 (①·"1."·"보기 1" → "1")
    quote_match: str = "strict"       # 0-2 인용 대조: strict = 원문 그대로, relaxed = "…" 분할·70% 이상 일치
    quote_min_ratio: float = 0.7
    links: bool = False               # 2-1~2-3 참조판례·참조조문 연결 지도 (data/raw/cases 원자료)
    link_k: int = 2                   # 진술당 연결로 더할 근거 수 (리랭커로 진술과 대조해 고름)
    link_min_score: float = 0.2       # 연결 근거의 리랭커 점수 하한
    link_candidates: int = 24         # 진술당 리랭커에 넣을 연결 후보 상한
    reverse_usage: bool = False       # 2-4 역방향 준용: 검색된 조문을 가져다 쓰는 조문도 연결 후보에
    merge_case_pieces: bool = False   # 2-5 판결요지 조각(~k)을 한 항목으로 합쳐 전달
    type_balance: bool = False        # 3-3 진술 근거에 조문이 없으면 순위 밖 조문 1개 보충
    research: bool = False            # 3-1 다시 찾는 검색: 유보·저확신·인용 불일치·동점 진술만 2차 검색 후 재판단
    research_conf: float = 0.85       # 3-1 이 확신도 미만이면 2차 검색 대상
    research_k: int = 4               # 3-1 진술당 새 근거 수 (이미 본 근거 제외)
    research_max_keys: int = 4        # 3-1 문항당 2차 검색 진술 상한
    count_tie: bool = False           # 5-1 개수형: 기대 개수가 두 보기 사이에 걸리면 유보·저확신 진술 재판단
    chapter_check: bool = False       # M1 조문 위치(편·장) 표시 + 회사 종류가 다른 장의 조문이면 그 조문을 준용하는 조문을 연결
    title_search: bool = False        # M2 진술에 조문 제목이 들어 있으면 그 조문을 연결 후보로
    # ---- v6 확장 (A-3, 프리셋 v6r 에서 켬) ----
    counter_check: bool = False       # 3-2 정답을 가르는 고확신 진술은 반대 근거를 찾아 2차 판단에 포함
    vote_n: int = 1                   # 4-1 근소 차 문항: 재판단을 N번 해서 다수결
    no_evidence_penalty: float = 1.0  # 4-3 근거 인용 없는 근거 판단의 확신도 배율 (1.0 = 표시만)
    recency_boost: float = 0.0        # 3-6 전원합의체·최근 판례 순위 가산 (0 = 끔)


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
    # --preset 을 생략했을 때 쓰는 선택형 풀이 구성 (configs/default.yaml 의 default_preset). 예전 v2 기본으로 돌리려면 "v2"
    default_preset: str = "v2"

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else ROOT / p

    def index_path(self) -> Path:
        """색인 폴더 (법령 스냅숏이면 index@<날짜>)."""
        base = self.resolve(self.paths.index_dir)
        snap = self.corpus.statute_snapshot
        return base.with_name(f"{base.name}@{snap}") if snap else base

    def raw_path(self, rel: str | Path) -> Path:
        """문서 목록의 원문 경로 (법령 스냅숏이면 statutes/ → statutes@<날짜>/)."""
        rel = Path(rel)
        snap = self.corpus.statute_snapshot
        if snap and rel.parts and rel.parts[0] == "statutes":
            rel = Path(f"statutes@{snap}", *rel.parts[1:])
        return self.resolve(self.paths.raw_dir) / rel

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

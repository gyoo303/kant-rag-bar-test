"""공통 설정. 실험 재현을 위해 실행 기록(results/<run_id>/config.json)에 이 값들을 함께 남긴다.

교안 기준값과 「프로젝트 결정」은 docs/course/STACK.md 참고.
환경변수로 덮어쓸 수 있는 값은 .env 에 적으면 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


# ── 시험 시점 (시험 이후 판례·개정 법령이 근거로 섞이지 않게) ─────────
# 2026년 제15회 변호사시험 기준. 빈 값("")이면 필터를 끈다.
LAW_AS_OF = _env("LAW_AS_OF", "20260101")        # 이 날짜에 시행 중이던 법령 버전 사용
PREC_DATE_FROM = _env("PREC_DATE_FROM", "")      # 판례 선고일 하한 (기본: 제한 없음)
PREC_DATE_TO = _env("PREC_DATE_TO", "20251231")  # 판례 선고일 상한 (시험일 이후 판례 제외)

# ── 경로 ─────────────────────────────────────────────
PREC_DIR = ROOT / "law_collector" / "data" / "prec"   # 수집한 판례 원문 (git 제외)
# 법령: collect.py laws --as-of <LAW_AS_OF> 로 받은 시점 버전 폴더. LAW_AS_OF 가 비면 현행(data/law)
LAW_DIR = ROOT / "law_collector" / "data" / (f"law_{LAW_AS_OF}" if LAW_AS_OF else "law")
INDEX_DIR = ROOT / "data" / "index"                   # chunks.jsonl, 메모리 벡터 저장소 (git 제외)
CACHE_DIR = ROOT / "cache"                            # 임베딩 캐시 (git 제외)
EVAL_DIR = ROOT / "eval"
RESULTS_DIR = ROOT / "results"

# ── 접속 정보 ────────────────────────────────────────
DATABASE_URL = _env("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/postgres")
# pgvector: 교안 2장 표준 / memory: 교안 1장 InMemoryVectorStore (Docker 없이 실행할 때)
VECTOR_BACKEND = _env("VECTOR_BACKEND", "pgvector")

# ── 모델 (교안 기준) ─────────────────────────────────
# 팀 통일 모델: gpt-6-luna (교안·발제의 gpt-5-mini 표기는 잘못된 것으로 팀 확인, 2026-11-23)
LLM_MODEL = _env("LLM_MODEL", "gpt-6-luna")
# gpt-6-luna 는 temperature 지정을 지원하지 않음(기본값 1만 허용) → none. 지원 모델이면 .env 에 숫자로
_t = _env("LLM_TEMPERATURE", "none").lower()
LLM_TEMPERATURE: float | None = None if _t in ("none", "") else float(_t)
LLM_TIMEOUT = 120          # 초. 넘으면 status=timeout
EMBEDDING_MODEL = "text-embedding-3-small"
RERANKER_MODEL = "Dongjin-kr/ko-reranker"
JUDGE_MODEL = _env("JUDGE_MODEL", "gpt-6-luna")  # RAGAS 판정용 (교안 7장은 gpt-4o-mini, 팀 모델로 통일)

# ── 청킹 ─────────────────────────────────────────────
# field: 판례의 원래 구조를 그대로 조각으로 (판시사항·판결요지를 [1][2]/가.나. 항목 단위로, 전문 제외,
#        참조조문·참조판례는 메타데이터로)  ← 팀 결정 기본값
# split: 교안 2장 RecursiveCharacterTextSplitter 로 모든 필드(전문 포함)를 500자 분할  ← 비교용
CHUNK_STRATEGY = _env("CHUNK_STRATEGY", "field")
INDEX_VERSION = _env("INDEX_VERSION", "v2")           # 청킹·색인 설정이 바뀌면 올린다
COLLECTION_NAME = f"civil_precedents_{INDEX_VERSION}_{CHUNK_STRATEGY}"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
PREC_SECTIONS = ("판시사항", "판결요지", "참조조문", "참조판례", "판례내용")   # split 전략
FIELD_SECTIONS = ("판시사항", "판결요지")                                    # field 전략: 조각이 되는 필드
# field 전략에서 판시사항·판결요지가 둘 다 없는 판례(주로 하급심): 기본은 제외하고 건수를 기록.
# true 면 판례 전문을 500자 분할해서 대신 넣는다.
FIELD_FULLTEXT_FALLBACK = _env("FIELD_FULLTEXT_FALLBACK", "false").lower() == "true"

# ── 검색 (STACK.md 「프로젝트 결정」) ────────────────
FIRST_STAGE_K = 20             # BM25·Vector 각각 1차 후보 수
FINAL_K = 5                    # 최종 근거 수 (Hit@5)
ENSEMBLE_WEIGHTS = (0.5, 0.5)  # (BM25, Vector) — 교안 5-3 기본값
RRF_C = 60                     # 교안 5-3 RRF 상수 (EnsembleRetriever 기본값과 동일)
BM25_TOKENIZER = _env("BM25_TOKENIZER", "whitespace")  # whitespace(교안) | kiwi(비교 실험)

# ── 근거 부족 판정 (개발셋으로 정한 뒤 고정. None 이면 사용 안 함) ──
# 교안 3-3: 벡터 코사인 거리 <= 0.60 만 근거로 인정 → 여기서는 유사도(1-거리) 기준으로 저장
MIN_VECTOR_SIMILARITY: float | None = None   # 예: 0.40 (= 거리 0.60)
MIN_RERANK_SCORE: float | None = None        # 예: 0.10 (C 구성 전용)

NO_EVIDENCE_MESSAGE = "제공된 판례·조문에서 확인할 수 없습니다."


def snapshot() -> dict:
    """실행 기록에 남길 설정 스냅샷."""
    return {
        "llm_model": LLM_MODEL,
        "llm_temperature": LLM_TEMPERATURE,
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "vector_backend": VECTOR_BACKEND,
        "index_version": INDEX_VERSION,
        "law_as_of": LAW_AS_OF,
        "prec_date_from": PREC_DATE_FROM,
        "prec_date_to": PREC_DATE_TO,
        "collection": COLLECTION_NAME,
        "chunk_strategy": CHUNK_STRATEGY,
        "field_fulltext_fallback": FIELD_FULLTEXT_FALLBACK,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "first_stage_k": FIRST_STAGE_K,
        "final_k": FINAL_K,
        "ensemble_weights": list(ENSEMBLE_WEIGHTS),
        "rrf_c": RRF_C,
        "bm25_tokenizer": BM25_TOKENIZER,
        "min_vector_similarity": MIN_VECTOR_SIMILARITY,
        "min_rerank_score": MIN_RERANK_SCORE,
    }

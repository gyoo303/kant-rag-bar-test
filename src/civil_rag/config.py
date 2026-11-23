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


# ── 경로 ─────────────────────────────────────────────
PREC_DIR = ROOT / "law_collector" / "data" / "prec"   # 수집한 판례 원문 (git 제외)
LAW_DIR = ROOT / "law_collector" / "data" / "law"     # 수집한 법령 원문 (git 제외)
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

# ── 청킹 (교안 2장 RecursiveCharacterTextSplitter) ───
INDEX_VERSION = _env("INDEX_VERSION", "v1")           # 청킹·색인 설정이 바뀌면 올린다
COLLECTION_NAME = f"civil_precedents_{INDEX_VERSION}"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
PREC_SECTIONS = ("판시사항", "판결요지", "참조조문", "참조판례", "판례내용")

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
        "collection": COLLECTION_NAME,
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

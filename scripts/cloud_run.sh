#!/usr/bin/env bash
# 클라우드 세션(GPU 없음)에서 색인 → 70문항 풀이까지 한 번에.
#   필요: 환경 설정의 환경변수 OPENAI_API_KEY (채팅에 붙여넣지 말 것)
#   사용: bash scripts/cloud_run.sh [라벨]    예) bash scripts/cloud_run.sh all70-cloud-v1
set -euo pipefail
cd "$(dirname "$0")/.."

: "${OPENAI_API_KEY:?OPENAI_API_KEY 가 없습니다. 클라우드 환경 설정 → 환경변수에 추가한 뒤 새 세션에서 실행하세요.}"
export KANT_RAG_CONFIG="${KANT_RAG_CONFIG:-configs/cloud.yaml}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"
export LLM_PROVIDER="${LLM_PROVIDER:-openai}"
export LLM_MODEL="${LLM_MODEL:-gpt-6-luna}"
LABEL="${1:-all70-cloud}"

echo "[1/4] 의존성 설치 (처음 한 번, 수 분)"
uv sync

echo "[2/4] 모델 호출 확인: $LLM_PROVIDER / $LLM_MODEL"
uv run python -c "
from kant_rag.config import get_settings
from kant_rag.generation.llm import get_chat_model
s = get_settings(); m = s.models
r = get_chat_model(m.llm_provider, m.llm_model, 64).invoke('한 단어로 답하세요: 대한민국의 수도는?')
print('  응답:', r.content if isinstance(r.content, str) else r.content)"

if [ ! -f index/index_info.json ] || ! grep -q "\"$EMBEDDING_MODEL\"" index/index_info.json; then
  echo "[3/4] 색인 생성 ($EMBEDDING_MODEL, 판례·법령 청크 약 3만 개 임베딩)"
  uv run kant-rag build-index
else
  echo "[3/4] 기존 색인 사용 ($EMBEDDING_MODEL)"
fi

echo "[4/4] 70문항 풀이 (구성 C: hybrid_rerank) → results/"
uv run kant-rag eval data/exam/2026_civil.json --modes hybrid_rerank --label "$LABEL"
echo "완료. 검색 없는 기준선: uv run kant-rag eval data/exam/2026_civil.json --modes closed_book --label ${LABEL}-closedbook"

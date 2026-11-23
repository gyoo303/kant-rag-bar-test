# kant-rag-bar-test — Knowledge Agent (프로젝트 3: RAG Agent)

업무 질문을 받으면 문서를 검색해 **확인 가능한 출처와 함께 답하거나, 근거가 부족하면 그렇다고 안내**하는 Knowledge Agent.
BM25 + Vector 하이브리드 검색, cross-encoder re-ranking, 캐싱/쿼리 리라이트, 고정 평가셋 기반 A/B/C 비교를 포함합니다.

## 구조
```
configs/default.yaml      실험 설정·버전 (단일 출처)
data/documents.csv        문서 목록 (doc_id, 제목, 출처, 이용 조건, 버전, 수집 시점, 경로)
data/raw/                 원문 (목록에 있는 파일만 색인)
docs/problem.md           문제·성공 기준 정의 (STEP 1)
docs/design.md            파이프라인·설정 설명
eval/dev.json, test.json  평가셋 (10 / 20문항) — 스키마는 eval/README.md
src/kant_rag/
  ingest/                 로딩·정제·청킹(원문 위치 보존)·색인 생성
  retrieval/              bm25 · vector(FAISS) · hybrid(RRF) · rerank · pipeline(A/B/C)
  generation/             프롬프트 · LLM · 근거 기반 답변(인용 검증)
  optimize/               cache(정확 일치) · rewrite(fallback 포함)
  evaluation/             평가셋 스키마 · 지표(Hit@5, 지연) · 실행기 · 캐시 실험
  agent.py                질문 → (리라이트) → 검색 → 답변 → 실행 기록
  cli.py                  명령줄
app/streamlit_app.py      실행 인터페이스
results/                  실행별 원본 기록(records.jsonl) · 채점표(grading.csv) · summary.json
report.md, contributions.md
```

## 설치
```bash
uv sync                    # Python 3.12, uv.lock 기준
cp .env.example .env       # API 키·모델 설정
```
- 생성 모델: 기본값 `anthropic / claude-opus-5-5` (`.env` 의 `LLM_PROVIDER`, `LLM_MODEL` 로 변경. OpenAI 사용 시 `uv sync --extra openai`)
- 임베딩 `BAAI/bge-m3`, reranker `BAAI/bge-reranker-v2-m3` — 로컬 실행 (첫 실행 시 HuggingFace 에서 다운로드)
- 한국어 형태소 BM25: `uv sync --extra ko` 후 `retrieval.bm25_tokenizer: kiwi`

## 실행
```bash
uv run kant-rag chunks                         # 청킹 결과·청크 ID 확인 (모델 불필요)
uv run kant-rag build-index                    # 색인 재생성 → index/
uv run kant-rag search "개봉 상품 반품" --mode hybrid   # 단계별 후보·점수
uv run kant-rag ask "개봉한 상품도 반품할 수 있나요?"     # 답변 + 출처 (기본 C)
uv run streamlit run app/streamlit_app.py      # UI
```

## 평가
```bash
uv run kant-rag check-eval                                       # 스키마·문항 구성 검사
uv run kant-rag eval eval/dev.json --label dev                   # 개발셋 A/B/C
uv run kant-rag eval eval/test.json --label final                # 최종 60건 (test.json frozen=true 필요)
uv run kant-rag eval eval/test.json --modes hybrid_rerank --rewrite --label final-rewrite   # C+리라이트 20건
uv run kant-rag grade results/<run_id>/grading.csv               # 사람 채점 집계
uv run pytest                                                    # 단위 테스트
```
- 품질 비교(A/B/C)는 캐시를 끈 상태에서만 실행됩니다. 캐시 검증 15건은 `kant_rag.evaluation.cache_experiment` 로 별도 수행.
- `results/<run_id>/records.jsonl` 에 실행 ID·질문 ID·구성·버전·단계별 후보/점수·재정렬 전후 순위·원본 답변·출처·시간·상태가 남습니다.
- 실패·재시도·추가 실험도 삭제하지 않고 `--label` 로 구분합니다.

## 버전 관리 규칙
- 문서·청킹·임베딩 변경 → `versions.docs` / `versions.index` 올리고 `build-index` 재실행, 평가셋 근거 ID 갱신
- 프롬프트 변경 → `versions.prompt`
- 최종 평가 전 `eval/test.json` 을 `frozen: true` 로 고정하고 커밋·태그
- 제출 태그: `ax1-project3-submit`

## 보안
`.env`, API 키, 개인정보, 무단 배포 문서, 모델 가중치, 색인(`index/`)은 커밋하지 않습니다. 문서 속 지시문은 데이터로만 취급합니다.

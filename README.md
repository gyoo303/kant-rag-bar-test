# kant-rag-bar-test — 민사법 RAG Agent (프로젝트 3: RAG Agent)

**2026년 제15회 변호사시험 민사법 선택형(70문항)** 을 조문·판례 검색 기반으로 풀이하는 Knowledge Agent.
보기(진술)마다 근거 조문을 검색해 정오를 판단하고, **근거 조문 ID 와 함께** 정답 번호를 제시하거나 근거가 부족하면 그렇다고 안내합니다.
BM25 + Vector 하이브리드 검색, cross-encoder re-ranking, 캐싱/쿼리 리라이트, 고정 평가셋 기반 A/B/C 비교를 포함합니다.

## 구조
```
configs/default.yaml      실험 설정·버전 (단일 출처)
data/documents.csv        문서 목록 (법령: doc_id, 제목, 출처, 이용 조건, 시행 버전, 수집 시점, 경로, doc_type)
data/raw/                 원문 — statutes/(법령) · cases/(판례 요지, 선택) · sample/
data/exam/                시험 문항·정답 (평가 입력 전용, 색인 금지)
scripts/fetch_law.py      국가법령정보센터 Open API 로 법령 수집 (시험일 기준 시행본)
docs/problem.md           문제·성공 기준 정의 (초안)
docs/design.md            파이프라인·설정
eval/dev.json, test.json  평가셋 (선택형 8+근거없음 2 / 선택형 17+근거없음 3) — eval/README.md
src/kant_rag/
  ingest/                 로딩·정제·청킹 (법령은 조문 단위: LAW-CIVIL#제750조)
  retrieval/              bm25 · vector(FAISS) · hybrid(RRF) · rerank · pipeline(A/B/C)
  generation/             자유 질의응답 (근거 인용 검증)
  mcq/                    선택형: 시험지 파싱 · 진술별 검색/판단 · 정답 결정 · 평가
  optimize/               cache(정확 일치) · rewrite(fallback 포함)
  evaluation/             공통 스키마 · 지표 · 캐시 실험
  agent.py, cli.py
app/streamlit_app.py      UI (질의응답 / 선택형 풀이 탭)
results/                  실행별 원본 기록 · 채점표 · summary.json
```

## 설치
```bash
uv sync
cp .env.example .env       # ANTHROPIC_API_KEY, LAW_OC 등
```
- 생성 모델 기본값 `anthropic / claude-opus-5-5` (`LLM_PROVIDER`, `LLM_MODEL` 로 변경, OpenAI 는 `uv sync --extra openai`)
- 임베딩 `BAAI/bge-m3`, reranker `BAAI/bge-reranker-v2-m3` — 로컬 실행
- 한국어 형태소 BM25: `uv sync --extra ko` 후 `retrieval.bm25_tokenizer: kiwi`

## 1) 데이터 준비
```bash
# 법령 수집 (시험일 기준 시행본) → data/raw/statutes/*.txt
uv run python scripts/fetch_law.py 민법 민사소송법 상법 민사집행법 주택임대차보호법 "상가건물 임대차보호법" "가등기담보 등에 관한 법률" --date 20260101
uv run kant-rag chunks          # 조문 청크·ID 확인
uv run kant-rag build-index     # 색인 재생성 → index/
```
수집 후 `data/documents.csv` 의 `version`(시행일자), `collected_at` 을 채우세요. 판례 요지는 `data/raw/cases/` 에 정리해 목록에 추가합니다.

## 2) 시험 문항 준비 (`data/exam/README.md`)
```bash
uv run kant-rag import-exam data/exam/2026_civil.txt --answers data/exam/2026_civil_answers.csv
uv run kant-rag split-exam data/exam/2026_civil.json     # eval/dev.json(8) · eval/test.json(17) · extra(45)
uv run kant-rag check-eval
```
이후 각 문항의 `type`(direct/paraphrase)·`evidence` 를 기입하고, 근거 없음 문항(dev 2 / test 3)을 작성한 뒤 `test.json` 을 `frozen: true` 로 고정합니다.

## 3) 풀이·평가
```bash
uv run kant-rag solve data/exam/2026_civil.json 12 --show-answer   # 문항 1개 (진술별 판단·근거 출력)
uv run kant-rag ask "불법행위 손해배상청구권의 소멸시효는?"          # 자유 질의응답
uv run kant-rag eval eval/dev.json --label dev                      # 개발셋 A/B/C
uv run kant-rag eval eval/test.json --label final                   # 최종: (17+3) × A/B/C = 60건
uv run kant-rag eval eval/test.json --modes hybrid_rerank --rewrite --label final-rewrite
uv run kant-rag grade results/<run_id>/grading.csv                  # 사람 채점(근거 적합·정보 부족 안내) 집계
uv run streamlit run app/streamlit_app.py
uv run pytest
```
- 정답률은 자동 채점(예측 번호 = 확정 정답), 근거 적합·근거 없음 대응은 `grading.csv` 에 사람이 0/1 기입 후 교차 검토합니다.
- `records.jsonl` 에 진술별 검색 후보·점수·재정렬 전후 순위, 진술별 판단·인용, 보기 점수, 시간, 상태가 남습니다.
- 품질 비교는 캐시를 끈 상태에서만 실행됩니다. 실패·재시도·추가 실험(extra 45문항 등)은 `--label` 로 분리합니다.

## 버전 관리 규칙
- 법령 재수집·청킹·임베딩 변경 → `versions.docs` / `versions.index` 올리고 `build-index`, 평가셋 근거 ID 확인
- 프롬프트 변경 → `versions.prompt`
- 최종 평가 전 `eval/test.json` 을 `frozen: true` 로 커밋, 제출 태그 `ax1-project3-submit`

## 보안·데이터
`.env`, API 키, 색인(`index/`)은 커밋하지 않습니다. 시험 문제·정답·해설은 색인·프롬프트에 넣지 않고, 수험서·해설서는 수집하지 않습니다. 문서 속 지시문은 데이터로만 취급합니다.

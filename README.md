# kant-rag-bar-test — AI 함정 문제를 푸는 민사법 RAG Agent (프로젝트 3: RAG Agent)

**2026년 제15회 변호사시험 민사법 선택형(70문항)** 을 조문·판례 검색 기반으로 풀이하는 Knowledge Agent.
보기(진술)마다 근거 조문을 검색해 정오를 판단하고, **근거 조문 ID 와 함께** 정답 번호를 제시하거나 근거가 부족하면 그렇다고 안내합니다.
BM25 + Vector 하이브리드 검색, cross-encoder re-ranking, 캐싱/쿼리 리라이트, 고정 평가셋 기반 A/B/C 비교를 포함합니다.

## 구조
```
configs/default.yaml      실험 설정·버전 (단일 출처)
data/documents.csv        문서 목록 (법령: doc_id, 제목, 출처, 이용 조건, 시행 버전, 수집 시점, 경로, doc_type)
data/raw/                 원문 — statutes/(법령) · cases/(판례 요지, 선택) · sample/
data/exam/                시험 문항·정답 (평가 입력 전용, 색인 금지)
data/cases/topics.txt     판례 검색 주제어 (법령 구조에서 자동 생성)
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

## 설치 (GPU PC 권장)
```bash
uv sync
cp .env.example .env       # OPENAI_API_KEY, LAW_OC 입력
```
- 생성 모델: OpenAI `gpt-6-luna` (`LLM_PROVIDER`, `LLM_MODEL` 로 변경 가능)
- 임베딩 `BAAI/bge-m3`, reranker `BAAI/bge-reranker-v2-m3` — 로컬 실행 (GPU 자동 사용, 첫 실행 시 약 4GB 다운로드)
- 한국어 형태소 BM25: `uv sync --extra ko` 후 `retrieval.bm25_tokenizer: kiwi`

## 1) 법령·판례 수집 → 색인 (**open.law.go.kr 에 IP 를 등록한 PC 에서 실행**)
국가법령정보센터 API 는 OC 에 등록된 IP/도메인에서만 응답합니다 (클라우드 세션·다른 PC 에서는 인증 실패).
```bash
uv run kant-rag api-check        # 연결·응답 구조 점검 (먼저 실행해서 결과 공유)
uv run kant-rag fetch-laws       # 문서 목록의 법령 → data/raw/statutes/ (2026-01-01 시행본), 목록에 시행일 기록
uv run kant-rag build-topics     # 법령 편/장/절·조문 제목 → data/cases/topics.txt (시험 문장 미사용)
uv run kant-rag fetch-cases --limit-topics 20   # 시험 수집
uv run kant-rag fetch-cases      # 전체 수집 (2011~2025 대법원, 주제어당 5건, 중단 후 재실행하면 이어받음)
uv run kant-rag import-cases <폴더|파일> --dry-run   # 팀이 따로 받은 판례: 먼저 통계만 확인
uv run kant-rag import-cases <폴더|파일>             # → data/raw/cases/cases_<연도>.jsonl (민사·가사, 2025년 이전, 판결요지만)
uv run kant-rag build-index      # 청킹 + BM25 + 벡터 색인 → index/
```
- 판례는 판결요지 항목 단위 청크(`CASE#2019다12345#2`), 법령은 조문 단위(`LAW-CIVIL#제126조`)입니다.
- 수집한 `data/raw/statutes/`, `data/raw/cases/cases.jsonl`, `data/cases/topics.txt` 는 커밋해 버전을 고정합니다 (공공저작물). `index/` 는 커밋하지 않고 재생성합니다.

## 2) 시험 문항 준비 (`data/exam/README.md`)
```bash
uv run kant-rag import-exam data/exam/2026_civil.txt --answers data/exam/2026_civil_answers.csv
uv run kant-rag split-exam data/exam/2026_civil.json     # eval/dev.json(8) · eval/test.json(17) · extra(45)
uv run kant-rag check-eval
```
이미 분리되어 있습니다 (dev 8 / test 17 / extra 45). 확정 정답은 `uv run kant-rag apply-answers <정답.csv>` 로 반영하고, 각 문항의 `type`(direct/paraphrase)·`evidence` 를 기입하고, 근거 없음 문항(dev 2 / test 3)을 작성한 뒤 `test.json` 을 `frozen: true` 로 고정합니다.

## 3) 풀이·평가
```bash
uv run kant-rag solve data/exam/2026_civil.json 12 --show-answer   # 문항 1개 (진술별 판단·근거 출력)
uv run kant-rag ask "불법행위 손해배상청구권의 소멸시효는?"          # 자유 질의응답
uv run kant-rag eval eval/dev.json --label dev                      # 개발셋 A/B/C
uv run kant-rag eval eval/test.json --label final                   # 최종: (17+3) × A/B/C = 60건
uv run kant-rag eval eval/test.json --modes closed_book --label final-closedbook  # 기준선: 검색 없는 풀이 17건
uv run kant-rag eval eval/test.json --modes hybrid_rerank --rewrite --label final-rewrite   # 선택 최적화: C+리라이트 20건
uv run kant-rag grade results/<run_id>/grading.csv                  # 사람 채점(근거 적합·정보 부족 안내) 집계
uv run kant-rag eval data/exam/2026_civil_tune.json --preset c --label tune-c   # 개선안 v3 (단계: v2·a1·a2·a34·b·c, docs/analysis/improvement-plan.md)
uv run kant-rag progress bar13-v3 --watch 60 --total 70             # 실행 중인 결과를 1분마다 표로 (다른 터미널에서)
uv run kant-rag eval data/exam/2026_civil_tune.json --modes hybrid_rerank --preset d --label tune-d   # 개선안 v4 (docs/analysis/improvement-plan-v4.md)
uv run kant-rag eval data/exam/<시험>.json --modes hybrid_rerank --preset v5 --label <라벨>   # 개선안 v5 (docs/analysis/improvement-plan-v5.md)
uv run streamlit run app/streamlit_app.py
uv run pytest
```
- 정답률은 자동 채점(예측 번호 = 확정 정답), 근거 적합·근거 없음 대응은 `grading.csv` 에 사람이 0/1 기입 후 교차 검토합니다.
- `records.jsonl` 에 진술별 검색 후보·점수·재정렬 전후 순위, 진술별 판단·인용, 보기 점수, 시간, 상태가 남습니다.
- 품질 비교는 캐시를 끈 상태에서만 실행됩니다. 실패·재시도·추가 실험(extra 45문항 등)은 `--label` 로 분리합니다.

## 클라우드 세션(Claude Code on the web, GPU 없음)에서 실행
1. 클라우드 환경 설정 → 환경변수에 `OPENAI_API_KEY` 추가 (채팅에 붙여넣지 말 것) → **새 세션**을 열어야 적용됨
2. 새 세션에서:
```bash
bash scripts/cloud_run.sh all70-cloud-v1
```
- 임베딩은 OpenAI `text-embedding-3-small` (GPU 불필요), 리랭커는 CPU → `configs/cloud.yaml` (후보 10개, 512토큰)
- 소요: 설치 수 분 + 임베딩 수 분 + 리랭커 약 40분 (70문항). 빠르게 보려면 `--modes hybrid` (리랭커 없음)
- 컨테이너가 끝나면 `index/` 는 사라짐 → `results/` 는 커밋·푸시해서 보존
- PC(GPU, bge-m3) 색인과 임베딩이 달라 결과가 다를 수 있음 → 비교 실험으로 기록

## 버전 관리 규칙
- 법령 재수집·청킹·임베딩 변경 → `versions.docs` / `versions.index` 올리고 `build-index`, 평가셋 근거 ID 확인
- 프롬프트 변경 → `versions.prompt`
- 최종 평가 전 `eval/test.json` 을 `frozen: true` 로 커밋, 제출 태그 `ax1-project3-submit`

## 보안·데이터
`.env`, API 키, 색인(`index/`)은 커밋하지 않습니다. 시험 문제·정답·해설은 색인·프롬프트에 넣지 않고, 수험서·해설서는 수집하지 않습니다. 문서 속 지시문은 데이터로만 취급합니다.

## 새 시험지 바로 풀기 (변환 단계 없음)
1. 메모장에 시험지 텍스트를 붙여넣고 UTF-8 로 저장 (예: `new_exam.txt`, 저장소 폴더)
2. 풀이: `uv run kant-rag solve-text new_exam.txt` (기본 `--preset v3`, `--preset b` 가능)
   - 정답이 있으면 채점: `--answers "3,5,5,1,…"` (1번부터 순서) 또는 `--answers 정답.csv`
3. 결과: 화면에 문항별 예측·진술 판단, `results/<시각>-text/answers.csv · records.jsonl · summary.json`
- 화면으로 보려면 `uv run streamlit run app/streamlit_app.py` → "선택형 풀이" 탭에 붙여넣기 (문항 여러 개 가능, 구성 선택)

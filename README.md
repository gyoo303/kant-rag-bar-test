# civil-law-rag — 민사법 판례 Knowledge Agent

변호사시험 민사법 질문에 대해 대법원 민사 판례·민법 조문을 검색하고, **출처와 함께 답하거나 근거 부족을 안내**하는 RAG.
팀 프로젝트 3 RAG · 구현은 수업 교안 「RAG 파이프라인 설계」 기준 ([docs/course/STACK.md](docs/course/STACK.md)).

## 빠른 시작
```powershell
# 1) 의존성 (uv 필요, Python 3.13 자동 설치)
uv sync

# 2) 환경변수
copy .env.example .env      # OPENAI_API_KEY 입력

# 3) 벡터 DB (PostgreSQL 17 + pgvector)
docker compose up -d

# 4) 판례 데이터 — law_collector/README.md 참고 (각자 OC로 분담 수집)
```

## 실행 순서
```powershell
# 0) 시험 시점 법령 받기 (한 번만)
python law_collector/collect.py laws --as-of 20260101

# 1) 원문 → 청크 (비용 없음). 기본으로 시험 시점 필터 적용(판례 ~2025-12-31, 법령 2026-01-01 시행본)
#    범위를 줄이려면 --limit / --keywords "임대차,소멸시효" / --court 대법원, 필터 끄기 --no-date-filter
uv run civil-rag ingest

# 2) 청크 → 벡터 색인 (OpenAI 임베딩 비용 발생, 캐시되므로 재색인은 무료)
uv run civil-rag index                      # pgvector (docker compose up -d 먼저)
uv run civil-rag index --backend memory     # Docker 없이 (.env 에 VECTOR_BACKEND=memory)

# 3) 검색만 확인 — 평가셋 근거 매핑할 때 (bm25 는 비용 없음)
uv run civil-rag search "임대차보증금 반환 동시이행" --mode bm25
uv run civil-rag search "임대차보증금 반환 동시이행" --mode C

# 4) 질문하기 / 화면
uv run civil-rag ask "…지문… 옳은가?" --config C
uv run streamlit run app/streamlit_app.py

# 5) 1단계: 시험지 풀기 (exams/README.md)
uv run civil-rag exam exams/<시험>.json --configs LLM A B C C+RW

# 6) 2단계: 고정 평가 (eval/README.md)
uv run civil-rag check-eval
uv run civil-rag eval --split test --configs A B C C+RW --strict
uv run civil-rag ragas results/<batch>/C --split test     # 보조 지표

# 테스트
uv run pytest -q
```

| 구성 | 내용 |
|---|---|
| `LLM` | 검색 없이 LLM 단독 (기준선) |
| `A` | Vector 상위 5 |
| `B` | BM25 20 + Vector 20 → 가중 RRF → 상위 5 |
| `C` | B 후보 20 → ko-reranker 재정렬 → 상위 5 |
| `C+RW` | C + 쿼리 리라이트 (원질문·변환 질의 기록, 실패 시 원질문) |

## 폴더 구조
```
src/civil_rag/
  config.py        모델·경로·검색 설정 (실행 기록에 같이 남김)
  ingest/          정제 · 청킹 · 메타데이터 · PGVector 색인
  retrieval/       A Vector / B BM25+Vector(RRF) / C +re-ranking / 쿼리 리라이트
  generation/      근거 주입 프롬프트 · 답변 · 출처 · 근거 부족 안내
  evaluation/      Hit@5 · 정답 충족 · 근거 적합 · 근거 없음 · 응답 시간 · RAGAS(보조)
  exam/            시험지(5지선다) 풀이·채점 — whole / per_choice 전략
  agent.py         질문 → 검색 → 답변 흐름, 구성(LLM/A/B/C/C+RW)
  cli.py           civil-rag 명령
app/               Streamlit 실행 화면
exams/             시험지 JSON (1단계)
tests/             단위 테스트
eval/              dev.json(10) · test.json(20, 고정) · 스키마
results/           실행별 원본 기록 (run_id 폴더)
docs/              problem.md · data_sources.md · course/(교안 정리)
law_collector/     open.law.go.kr 판례·법령 수집기
report.md          비교 보고서
contributions.md   팀원별 기여·재실행 기록
```

## 작업 규칙 (Git)
- 각자 **브랜치**에서 작업 → `main`에는 **PR + 리뷰 1명 이상**으로만 merge
- 브랜치 이름: `feat/…`, `fix/…`, `eval/…`, `docs/…` (예: `feat/hybrid-retriever`)
- 시작 전 `git switch main` → `git pull` → `git switch -c feat/작업명`
- 커밋 금지: `.env`, `law_collector/state/`, 판례 원문(`law_collector/data/prec/`) — 원문은 공유 드라이브
- `eval/test.json`은 고정 후 수정 금지

## 진행 계획
1. 수업 범위 RAG(A/B/C)로 기출 기반 개발셋 점수 최대화
2. 같은 RAG로 변형 시험(최종 평가셋) 측정 — A/B/C × 20 = 60건 + 쿼리 리라이트 20건
3. Agentic RAG 추가 실험 (본 평가와 분리)

## 데이터 출처
법제처 국가법령정보센터 (open.law.go.kr) — 상세는 [docs/data_sources.md](docs/data_sources.md)

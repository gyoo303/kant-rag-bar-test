# 프로젝트 3 RAG — 민사법 판례 Knowledge Agent

원본 요구사항: 노션 「프로젝트 3 RAG」 https://app.notion.com/p/4215caf56ec88079b35fec55acda7df0
(요구사항이 바뀌면 노션이 기준. 아래는 작업용 요약)

## 우리 팀 주제
- 사용자: 변호사시험 민사법 수험생 / 신입 변호사
- 문제: 민법 조문·대법원 판례를 찾느라 걸리는 시간, 유사 법리 혼동(무효/취소, 해제/해지 등)으로 인한 오답
- 문서: 법제처 국가법령정보 공동활용(open.law.go.kr) 민사 판례(데이터출처 "대법원" 42,537건) + 민법 등 조문
- 팀 3명. 수집기: `law_collector/` (판례일련번호 % 3 으로 분담)

## 팀 진행 계획 (초안, 2026-11-23)
평가셋은 변호사시험 민사법 시험지 기반.
1. 수업 범위 RAG(A/B/C)로 **기본 시험(기출)** 점수 최대화 [2일] → 기출 = 개발셋(튜닝 허용)
2. 같은 RAG로 **변형 시험** 점수 측정 [1일] → 변형 = 최종 평가셋(튜닝 금지, 사전 고정)
3. **Agentic RAG**로 변형 시험 측정 [1일] → 필수 평가와 분리된 추가 실험으로 보고
보완 필요: 근거 없음 문항(dev 2 / test 3), 캐싱 또는 쿼리 리라이트 1개, 문항별 허용 근거(판례·조문) 매핑, RAG 없는 LLM 단독 기준선

## 코드 구조 (2026-11-23 구현)
- `uv run civil-rag ingest|index|search|ask|exam|check-eval|eval|ragas` — 사용법은 README.md
- 구성 `LLM`(기준선) / `A` / `B` / `C` / `C+RW` 은 `src/civil_rag/agent.py` RUN_CONFIGS
- 1단계 시험지: `exams/*.json` + `civil-rag exam` (whole / per_choice 전략)
- 2단계 고정 평가: `eval/test.json` + `civil-rag eval`
- **생성·판정 모델은 팀 통일 `gpt-6-luna`** (교안·발제의 gpt-5-mini/gpt-4o-mini 표기는 잘못된 것으로 팀 확인). temperature 미지원이라 지정하지 않음

## 필수 범위 (평가 기준)
- 업무 문제 정의 → `docs/problem.md` (사용자, 기존 탐색 과정, 오답 영향, RAG 이유, 제외 범위, 품질·지연·비용 우선순위와 목표값을 결과 보기 전에 확정)
- 문서 목록: 문서 ID, 제목, 출처, 이용 조건, 버전/수집 시점, 원문 위치
- 청크: 안정적인 청크 ID + 문서 ID + 원문 위치(판례는 판시사항/판결요지/이유 등 절 단위)
- 검색 3단계 비교
  - A: Vector only
  - B: BM25 + Vector 하이브리드 (RRF 등 명시적 결합, 점수 단순 합산 금지)
  - C: B + re-ranking (reranker로 질의–청크 관련도 재평가)
- 근거 기반 답변: 실제 검색된 청크만 인용, 근거 부족 시 "정보 부족" 안내, 호출 오류와 "근거 없음" 구분
- 최적화 1개 필수: 캐싱(15건 검증) 또는 쿼리 리라이트(C vs C+리라이트 20건)
- 평가셋 30문항: `eval/dev.json` 10 (답변가능 8 + 근거없음 2), `eval/test.json` 20 (직접검색 10 + 표현변형/유사조건 7 + 근거없음 3). test는 튜닝에 쓰지 않고 버전 고정
- 최종 평가: A/B/C × 20 = 60건. Hit@5(/17), 정답 충족(/17), 근거 적합(/17), 근거없음 대응(/3), 호출 성공 수, 응답시간 평균·중앙값, 오류·timeout
- 실행 기록: 실행 ID·질문 ID·구성·버전·후보/점수·재정렬 전후 순위·답변·출처·시간·상태·채점 근거 → `results/` JSON/CSV
- 인터페이스: Streamlit 또는 API 1개 (UI 완성도 경쟁 아님)
- 산출물: `src/`, `pyproject.toml`/requirements, `.env.example`, README, `docs/`, `eval/`, `results/`, `report.md`, `contributions.md`, 태그 `ax1-project3-submit`
- 다른 팀원이 README만 보고 색인 재생성·대표 사례 재실행 가능해야 함

## 제외 / 금지
- 모델 학습·파인튜닝, 외부 시스템 쓰기·실제 업무 실행
- 평가 정답표를 색인이나 프롬프트에 넣기, 실패 삭제·좋은 재실행만 고르기
- API 키·`.env`·대용량 원문을 저장소에 올리기 (대용량은 위치·재생성 방법만 기록)
- 파일 개수는 성과가 아님 → 코퍼스 크기보다 신뢰성 있는 검증이 중요

## 일정 (5일 / 40시간)
1일차 문제·범위·평가셋 → 2일차 전처리·색인·A/B → 3일차 re-ranking·답변·최적화·UI, 설정 고정 → 4일차 고정 평가 60건·채점·실패 분석 → 5일차 보고서·재현·발표

## Git 작업 규칙 (팀 합의)
- 각자 **브랜치를 만들어 작업**하고, `main`에는 PR로만 합친다 (main 직접 push 금지)
- 브랜치 이름: `feat/<작업>`, `fix/<작업>`, `eval/<작업>`, `docs/<작업>` (예: `feat/hybrid-retriever`, `eval/test-set-v1`)
- PR마다 다른 팀원 1명 이상 리뷰 → 노션 평가의 "개인별 코드 기여·PR·리뷰 근거"로 쓰임
- 작업 시작 전 `main` 최신화 후 브랜치 생성, 한 브랜치 = 한 작업 단위
- `eval/test.json`은 고정 후 수정 금지 (바꿔야 하면 PR에 사유 기록, 버전 올림)
- `.env`, `state/`, 대용량 판례 원문은 커밋하지 않음

## 기술 기본값 — 교안 기준
**구현은 수업 교안 「RAG 파이프라인 설계」 방식을 따른다.** 기준표: [docs/course/STACK.md](docs/course/STACK.md) (장별 상세: docs/course/ch*.md)
- uv + Python 3.13, LangChain LCEL, gpt-6-luna(팀 통일), text-embedding-3-small, PostgreSQL17+pgvector(PGVector), BM25Retriever + EnsembleRetriever(RRF), CrossEncoderReranker(Dongjin-kr/ko-reranker), RAGAS
- 교안에 없거나 교안끼리 어긋나는 부분만 STACK.md 「프로젝트 결정」대로 하고, 바꾼 이유를 report.md에 남긴다
- 교안 코드의 알려진 결함(STACK.md 3절)은 그대로 복사하지 않는다
- 문서(판례) 속 지시문은 신뢰하지 않는 데이터로 취급

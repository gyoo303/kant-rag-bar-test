# ADR-006: 영속 계층 (원문·청크·벡터·수집 상태)
- 상태: Accepted (user, 2026-11-23) — 옵션 C(PostgreSQL), 세부: Docker Compose 실행 · pgvector · psycopg 3 + SQL
- 관련 계층: [인프라] [레이어]
- 근거: DRV-Q-01, DRV-Q-04, RISK-01, RISK-03, RISK-12, RISK-13, RISK-16, REQ-076, REQ-097, C-13, AQ-009

## 맥락
저장할 것은 ① 수집 원문(민법 조문 약 1,100개 + 판례 4만 건)과 수집 진행 상태(멈춰도 이어받기, RISK-03·13), ② 청크와 메타데이터, ③ 벡터(최대 약 12만 × 1536차원), ④ 평가셋·실행 기록(제출물, C-13).

## 검토한 옵션
| 옵션 | 장점 | 단점 | AI 부채 영향 | 외부 기준 영향 | 되돌리기 비용 |
|---|---|---|---|---|---|
| A. 모두 파일(JSONL) | 의존성 없음 | 이어받기·중복 제거 직접 구현 | 중 | 중립 | 낮음 |
| B. SQLite + 결과 파일 | 설치 없음, 이어받기 쉬움 | 벡터는 별도 저장소 필요 | 낮음 | 중립 | 중 |
| C. PostgreSQL(+pgvector)로 원문·청크·벡터 통합, 평가셋·결과는 파일 | 저장소 하나, 청크 ID로 벡터·BM25·원문 연결, SQL 학습 연결(DOC-01 §3) | DB 서버 실행 필요 | 낮음(Docker로 재현) | CRT-03·14 | 높음 |

## 결정 (사용자 선택 C와 세부 답, 2026-11-23)
- **실행**: 저장소 루트 `compose.yaml`의 서비스 `db`, 이미지 `pgvector/pgvector:pg17`, 포트 `5432`, 이름 있는 볼륨 `lawqa_pgdata`. 기동 `docker compose up -d db`. 접속 값은 `.env`의 `DATABASE_URL`(ADR-003에 항목 추가: `.env.example`에 이름만).
- **데이터베이스**: 개발·평가용 `lawqa`, 시험용 `lawqa_test`(저장 계층 시험이 매 세션 스키마를 새로 만든다).
- **확장**: `CREATE EXTENSION IF NOT EXISTS vector`.
- **데이터 접근**: `psycopg` 3(동기) + `pgvector` 파이썬 어댑터, SQL 직접 작성. ORM 없음.
- **스키마 반영**: `src/lawqa/corpus/infrastructure/schema.sql`(그리고 각 모듈 필요 시 같은 이름 파일)을 `python -m lawqa db init`이 실행. 모든 문장은 `IF NOT EXISTS`. 마이그레이션 도구 없음. 스키마가 바뀌면 청크·벡터 테이블만 다시 만들고 원문 테이블(`source_documents`)은 보존한다(A3에서 분리).
- **평가셋·결과**: DB에 넣지 않는다. `eval/*.json`, `results/<run_id>/`(커밋). `evaluation` 모듈만 읽는다(ADR-001).
- **경계**: 저장소 클래스(`infrastructure`)가 행을 도메인 객체로 바꿔 돌려준다. `psycopg` 행·커서는 `infrastructure` 밖으로 나가지 않는다(RISK-16).
- **트랜잭션**: 저장소 메서드 호출 단위가 아니라 응용 서비스 단위(A5).

## 결과
- 좋아지는 점: 원문·청크·벡터가 한 저장소, 이어받기·중복 제거를 PK·`ON CONFLICT`로 해결
- 감수할 점: Docker Desktop 실행 필요, DB 볼륨은 저장소에 커밋하지 않으므로 재현은 "수집 → 색인" 명령으로 함(README·`data/MANIFEST.md`)
- 후속 작업: A3 테이블 정의, TKT-DB(compose·연결·스키마·저장소)

## 쉬운 설명
- A. 전부 파일: 무엇이 달라지나 — 받은 법령·판례를 줄 단위 파일에 쌓는다. / 좋은 점 — 설치가 없다. / 감수할 점 — 이어받기·중복 막기를 직접 만든다. / 나중에 바꾸기: 쉬움.
- B. 파일형 DB(SQLite): 무엇이 달라지나 — 파일 하나짜리 DB에 저장한다. / 좋은 점 — 설치가 없다. / 감수할 점 — 벡터는 다른 저장소에 따로 둔다. / 나중에 바꾸기: 보통.
- C. PostgreSQL(선택): 무엇이 달라지나 — Docker로 DB 서버를 띄우고 원문·청크·벡터를 모두 넣는다. / 좋은 점 — 한곳에서 관리하고 SQL로 확인하기 쉽다. / 감수할 점 — Docker를 켜야 한다. / 나중에 바꾸기: 어려움.

## 개정
- 2026-11-23: ADR-007(가져오기)·ADR-009(PGVector 표준 클래스)로 세부 수정(§2-8 ②): 수집 진행 상태 대신 가져오기 멱등(ON CONFLICT), 벡터는 langchain-postgres가 관리하는 `langchain_pg_embedding` 표에 청크 ID를 문서 ID로 저장.

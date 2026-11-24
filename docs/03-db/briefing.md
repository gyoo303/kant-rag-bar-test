---
stage: DB
tickets: [TKT-DB-M1-01]
status: done
inputs_read: [AR-MAP, AR-HAND, AR-DB, AR-API, AR-CONV, AR-GATE, CR-LOG]
next_readers: [BE, QA]
---
# DB 에이전트 브리핑

## 처리한 티켓
| TKT | 완료 조건 | 충족 여부 |
|---|---|---|
| TKT-DB-M1-01 | `init_schema`가 빈 DB에 두 번 실행해도 오류 없음 | 충족 — 시험 `test_init_schema_twice_on_fresh_db_no_error`, 개발 DB `lawqa`에도 두 번 실행해 표 4개 확인 |
| TKT-DB-M1-01 | GATE-04b | 충족 — `uv run pytest tests/integration -q` 17 passed |
| TKT-DB-M1-01 | CHECK 제약 시험(판례 본문 없음 거부) | 충족 — `test_precedent_without_holdings_and_summary_rejected`(NULL·빈 문자열·공백 3경우) |

### TKT-DB-M1-01

## 만든 것
- `compose.yaml`: 서비스 `db`(`pgvector/pgvector:pg17`), 사용자·DB `lawqa`, 비밀번호 `${POSTGRES_PASSWORD}`(없으면 기동 거부), 볼륨 `lawqa_pgdata`, 첫 기동 때 `lawqa_test` DB 생성(compose `configs` 인라인 SQL), 상태 확인 `pg_isready`. 호스트 포트 `${POSTGRES_PORT:-5432}`(아래 "설계와 다르게 한 것").
- `src/lawqa/corpus/infrastructure/schema.sql`: `vector` 확장 + 표 4개. 모든 문장 `IF NOT EXISTS`. PGVector 표는 정의하지 않음(ADR-009).

| 표 | 제약·색인 이름 | 근거 |
|---|---|---|
| `source_documents` | `source_documents_pkey`, `source_documents_kind_check`, `source_documents_precedent_content_check`(판례는 판시사항·판결요지 중 하나가 공백 아님), `source_documents_statute_content_check`(조문은 `body`·`article_no` 필수), `article_branch_no` 기본 0 | INV-02, 03-db-schema §3 |
| `index_versions` | `index_versions_pkey`, `index_versions_max_chars_check`(>0), `index_versions_overlap_chars_check`(>=0) | INV-11 |
| `chunks` | `chunks_pkey`(index_version, chunk_id), `chunks_index_version_fkey`(ON DELETE CASCADE), `chunks_doc_id_fkey`(ON DELETE RESTRICT), `chunks_kind_check`, `chunks_section_check`, `chunks_seq_check`(>=1), `chunks_text_check`(길이>0), 색인 `chunks_index_version_doc_id_idx` | INV-02 |
| `import_issues` | `import_issues_pkey`(identity), **`corpus_version` 컬럼 + 색인 `import_issues_corpus_version_idx`, FK 없음**(CR-007) | REJ-06, CR-007 |

- `src/lawqa/shared/db.py`: `connect(url) -> psycopg.Connection`, `read_schema_sql() -> str`(패키지 자원에서 읽음), `init_schema(conn) -> None`(한 트랜잭션으로 실행).
- `tests/conftest.py`: `db_url`(설정의 `DATABASE_URL_TEST`, 비면 실패), `fresh_schema`(세션마다 `public` 스키마를 지우고 `init_schema` — **DB 이름이 `_test`로 끝나지 않으면 거부**), `db_conn`(시험 하나 끝나면 rollback).
- `tests/integration/db/test_schema.py`: 17개(두 번 실행, 확장, PGVector 표 없음, 판례·조문 CHECK, 종류 CHECK, 청크 FK·CHECK, 판본 삭제 CASCADE, `import_issues` CR-007).
- 데이터 접근 계층(저장소 클래스): 이 티켓 범위 아님(TKT-DB-M1-02, TKT-DB-M2-01·02).

## 인프라 확인 포인트
- 환경변수(`.env`): `POSTGRES_PASSWORD`, `DATABASE_URL`(`…/lawqa`), `DATABASE_URL_TEST`(`…/lawqa_test`), 선택 `POSTGRES_PORT`. 형식은 `.env.example`.
- 기동: `docker compose up -d db` → `docker compose ps`에서 `healthy` 확인.
- `lawqa_test` DB는 **볼륨이 비어 있는 첫 기동 때만** 만들어진다. 볼륨이 이미 있는데 `lawqa_test`가 없으면 `docker compose exec db psql -U lawqa -d lawqa -c "CREATE DATABASE lawqa_test OWNER lawqa;"`로 만든다.
- 스키마 반영: `init_schema`(명령 `python -m lawqa db init`은 TKT-BE-M1-02에서 연결). `IF NOT EXISTS`라 이미 있는 표의 컬럼·제약 변경은 반영되지 않는다 — 스키마가 바뀌면 `chunks`·`index_versions`·`import_issues`만 지우고 다시 만든다(원문 `source_documents` 보존, ADR-006).
- 시드: 없음(운영 데이터는 가져오기, 시험 데이터는 TKT-DB-M2-01).

## 다음 단계(BE)가 쓸 것
- `from lawqa.shared.db import connect, init_schema` — `with connect(settings.secrets.require("database_url")) as conn: init_schema(conn)`.
- 트랜잭션 확정은 응용 서비스가 `with conn.transaction():`로 연다(04-interfaces-api §10). `init_schema`만 자체 트랜잭션을 쓴다.
- 제약 위반 예외: `psycopg.errors.CheckViolation`, `ForeignKeyViolation` 그대로(도메인 예외 변환은 설계에 없음 — 저장소 티켓에서 필요한 경우만).
- **CR-007(승인, ARCH 미반영)**: 가져오기 문제 기록은 `corpus_version`으로 묶는다. `ImportService`는 색인 판본 없이 저장하고, `IndexService`는 `count(corpus_version)`을 `skipped_count`로 쓴다.

## 구현 중 자율 결정
#### TKT-DB-M1-01 제약 이름
- 결정: 모든 제약·색인에 `<표>_<컬럼|의미>_<pkey|fkey|check|idx>` 이름을 붙임 — 03-db-schema §3(이름 미지정)
- 선택지: **A. 명시 이름 (권장·채택)** / B. PostgreSQL 자동 이름
- 권장 이유: 시험과 오류 메시지에서 어떤 규칙이 막았는지 바로 보인다.
- trade-off: A — 이름을 바꾸려면 표를 다시 만들어야 함. B — 자동 이름이 버전마다 달라질 수 있음.

#### TKT-DB-M1-01 `lawqa_test` 생성 방법
- 결정: compose `configs`의 인라인 SQL을 `/docker-entrypoint-initdb.d/`에 넣음 — 티켓 산출이 `compose.yaml` 하나
- 선택지: **A. compose 인라인 (권장·채택)** / B. 별도 SQL 파일 마운트 / C. 시험 픽스처가 생성
- 권장 이유: 파일을 늘리지 않고 compose 하나로 두 DB가 준비된다.
- trade-off: A — 볼륨이 이미 있으면 실행되지 않음(수동 명령 안내). B — AGENTS 표에 없는 파일 추가. C — 시험이 DB 권한을 더 필요로 함.

#### TKT-DB-M1-01 시험 DB 보호
- 결정: `fresh_schema`가 DB 이름이 `_test`로 끝나지 않으면 실패 — ADR-006(시험은 `lawqa_test`)
- 선택지: **A. 이름 검사 (권장·채택)** / B. 검사 없음
- 권장 이유: 잘못된 접속 문자열로 개발 DB의 원문이 지워지는 사고를 막는다.
- trade-off: A — 다른 이름의 시험 DB를 쓰려면 `_test`로 끝나야 함. B — 사고 위험.

#### TKT-DB-M1-01 `DATABASE_URL_TEST` 없을 때
- 결정: 통합 시험이 skip이 아니라 실패 — GATE-04b("실패 0")
- 선택지: **A. 실패 (권장·채택)** / B. skip
- 권장 이유: DB 없이 돌려 "통과"로 보이는 것을 막는다.
- trade-off: A — DB 없이 `pytest` 전체를 돌리면 통합 시험이 실패(단위 시험만은 `tests/unit`). B — 게이트가 거짓 통과할 수 있음.

## 설계와 다르게 한 것 / 질문
- **CR-007(사용자 승인 2026-11-24, 대상 ARCH)**: `import_issues.index_version`(FK → index_versions) 대신 `corpus_version`(FK 없음)으로 구현. 이유: 가져오기(SEQ-01)가 색인(SEQ-02)보다 먼저 실행되어 FK를 만족할 수 없음. ARCH 문서 반영 필요.
- **호스트 포트(ARCH에 알림)**: ADR-006은 포트 `5432`. 이 PC에서는 다른 프로젝트 컨테이너(`kant-ch3-backend-restful-api-db-1`)가 5432를 쓰고 있어 `"${POSTGRES_PORT:-5432}:5432"`로 바꿨다. 기본값은 설계와 같고, 이 PC의 `.env`는 `POSTGRES_PORT=5433`과 5433 접속 문자열을 쓴다. ADR-006에 "호스트 포트는 `POSTGRES_PORT`로 바꿀 수 있음" 한 줄 추가를 요청한다(다른 컨테이너는 건드리지 않음).
- `.env`: 사용자 동의(2026-11-24)로 로컬 전용 무작위 비밀번호를 만들어 `POSTGRES_PASSWORD`·`DATABASE_URL`·`DATABASE_URL_TEST`를 채움(값은 출력·커밋하지 않음). 기존 `DATABASE_URL` 값은 덮어씀.

## 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-01(DB 부분) | `docker compose up -d db` → 상태 확인 | `healthy`, DB `lawqa`·`lawqa_test` 존재 |
| 완료 조건 | `init_schema` 두 번(개발 DB `lawqa`) | 오류 없음, 표 `chunks`·`import_issues`·`index_versions`·`source_documents` |
| GATE-04b | `uv run pytest tests/integration -q` | 17 passed |
| GATE-04 | `uv run pytest tests/unit -q` | 15 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-06 | `git ls-files .env`, 키·비밀번호 패턴 `git grep` | 0줄, 0줄 |
| GATE-07 | 빈 except `git grep` | 0줄 |
| GATE-08 | `application`·`domain`의 `psycopg`·LangChain import | 0줄 |

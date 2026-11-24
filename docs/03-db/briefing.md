---
stage: DB
tickets: [TKT-DB-M1-01, TKT-DB-M1-02, TKT-DB-M2-01]
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

---

### TKT-DB-M1-02 (평가 파일 저장소)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 |
|---|---|---|
| TKT-DB-M1-02 | 기록 중단 후 다시 열어도 기존 줄 유지 | 충족 — `test_run_store_reopen_after_interruption_keeps_existing_lines`(새 저장소 객체로 이어 쓰기), 잘린 마지막 줄은 고치지 않고 파일·줄 번호로 보고(`test_run_store_truncated_last_line_reported_not_repaired`) |
| TKT-DB-M1-02 | `RunStore.append`가 줄 단위 JSON | 충족 — `test_run_store_append_writes_one_json_line_per_record`(LF 줄 끝, 한 줄 = 문항 1건) |
| TKT-DB-M1-02 | GATE-04b·08 | 충족 — §검증 결과 |

#### 만든 것 (`src/lawqa/evaluation/infrastructure/files.py`)
| 클래스 | 메서드 시그니처 | 반환 |
|---|---|---|
| `JsonEvalSetRepository(eval_dir)` | `load(split: Split)` | `EvalSet` (`<eval_dir>/<split>.json`, 검증은 `EvalSet.from_dict`) |
| `SuccessCriteriaFile(path)` | `load()` | `SuccessCriteria` |
| `FreezeFile(path)` | `load()` / `save(record: FreezeRecord)` | `FreezeRecord \| None` / `None`(임시 파일 후 교체로 원자적 쓰기) |
| `RunStore(results_dir)` | `create(run: Run)` | `None` — `run.json`을 배타 생성(`open("x")`), 이미 있으면 `FileExistsError`(`--resume` 안내) |
| | `append(record: RunRecord)` | `None` — `records.jsonl`에 한 줄 + `flush`·`fsync`, `run.json` 없으면 `FileNotFoundError` |
| | `append_grade(grade: Grade)` | `None` — `grades.jsonl`에 한 줄 |
| | `load(run_id: str)` | `tuple[Run, list[RunRecord]]` |
| | `load_grades(run_id: str)` | `list[Grade]` (설계 §7에 없음, 아래 질문) |
| | `run_dir(run_id)`, `exists(run_id)` | `Path`, `bool` (`--resume`·중복 확인용) |
- 파일이 없거나 JSON이 깨지면 `InvalidEvalDataError`(입력 오류, 종료 코드 1) — 파일 경로와 줄 번호 포함.
- `RunRecord` 직렬화: 03-db-schema §5 고정 필드 14개는 그대로, 검색·답변 상세(`queries`, `candidates`, `raw_output` 등)는 `details`를 같은 줄에 펼쳐 씀. 읽을 때 고정 필드 밖의 키는 `details`로 돌려줌. `details`가 고정 필드 이름과 겹치면 거부.
- DB(PostgreSQL)는 쓰지 않음(ADR-006: 평가셋·결과는 커밋 파일).

#### 인프라 확인 포인트
- 경로는 설정 `[paths] eval_dir`, `results_dir`(`config/base.toml`)에서 받는다.
- 기록 파일은 UTF-8, 줄 끝 LF로 쓴다(Windows에서도). `.gitattributes`의 CRLF 변환 경고가 커밋 때 나올 수 있으나 내용은 같다.
- 실행이 쓰는 중에 멈춰 마지막 줄이 잘리면 `load`가 "마지막 줄이 잘림"으로 멈춘다. 사람이 그 줄을 확인하고 지운 뒤 `--resume`한다(자동 수정하지 않음 — 금지 패턴 13).

#### 다음 단계(BE)가 쓸 것
- `FreezeService`(TKT-BE-M1-04): `FreezeFile(settings.paths.eval_dir / "FREEZE.json")`, `SuccessCriteriaFile(eval_dir / "success_criteria.json")`, `JsonEvalSetRepository(eval_dir)`.
- `EvalRunService`(TKT-BE-M3-05): `RunStore(settings.paths.results_dir)` — `exists`로 중복 확인 후 `create`, 문항마다 `append`. `--resume`이면 `load`로 이미 기록된 `question_id`를 빼고 `append`만.
- 트랜잭션 개념 없음: `append` 한 번이 한 줄의 확정이다.

#### 구현 중 자율 결정
##### TKT-DB-M1-02 잘린 마지막 줄 처리
- 결정: 읽을 때 오류로 멈추고 파일은 고치지 않음 — INV-07, 금지 패턴 13
- 선택지: **A. 오류로 보고 (권장·채택)** / B. 잘린 줄을 조용히 건너뜀 / C. 자동으로 지움
- 권장 이유: 기록 누락이 지표 분모를 바꾸므로 사람이 알아야 한다. 자동 수정은 "기존 줄 수정 금지"에 어긋난다.
- trade-off: A — 드물게 사람이 한 줄을 정리해야 함. B — 누락이 숨겨짐. C — 기록을 코드가 바꿈.

##### TKT-DB-M1-02 `run.json` 배타 생성
- 결정: `open("x")`로 만들어 이미 있으면 실패 — 04-interfaces-api §10("같은 run_id 두 번은 --resume 없이 거부")
- 선택지: **A. 배타 생성 (권장·채택)** / B. 존재 확인 후 쓰기
- 권장 이유: 확인과 쓰기 사이의 경쟁 없이 한 번에 막는다.
- trade-off: A — 실패 시 폴더는 남을 수 있음(내용은 그대로). B — 확인 뒤 덮어쓸 틈이 생김.

#### 설계와 다르게 한 것 / 질문
- **`RunStore.load_grades(run_id)` 추가**: 03-db-schema §7 메서드 목록에는 없다. `grades.jsonl`을 쓰기만 하고 읽는 방법이 없으면 `eval metrics`(TKT-BE-M4-02)가 파일을 직접 읽어야 해서 추가했다. → ARCH에 §7 목록 추가 요청.
- `run_dir`·`exists` 보조 메서드 추가(같은 이유: `--resume`·중복 확인).

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-04b | `uv run pytest tests/integration -q` | 29 passed(이번 티켓 12개 추가) |
| GATE-04 | `uv run pytest tests/unit -q` | 81 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-07 | 빈 except | 0줄 |
| GATE-08 | `application`·`domain`의 저장 계층 import | 0줄 |
| GATE-09 | `corpus`·`retrieval`·`answering`의 정답 경로 | 0줄 |

---

### TKT-DB-M2-01 (원문·청크·판본·이슈 저장소)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 |
|---|---|---|
| TKT-DB-M2-01 | upsert 멱등 | 충족 — `test_upsert_many_is_idempotent_and_updates_content` |
| TKT-DB-M2-01 | `replace_for_version` 교체 | 충족 — `test_replace_for_version_replaces_only_that_version`(다른 판본은 그대로, 다른 판본 청크 섞이면 거부) |
| TKT-DB-M2-01 | 행 → 도메인 변환 | 충족 — `test_iter_all_returns_equal_domain_objects`, `test_list_and_get_many_round_trip` |
| TKT-DB-M2-01 | AC-05-3 같은 입력 두 번 → 같은 청크 ID 집합 | 충족 — `test_ac_05_3_…` |
| TKT-DB-M2-01 | GATE-04b·08 | 충족 — §검증 결과 |

#### 만든 것
| 클래스 | 메서드 시그니처 | 반환 |
|---|---|---|
| `PgSourceDocumentRepository(conn)` | `upsert_many(docs: list[SourceDocument])` | `int` — `ON CONFLICT (doc_id) DO UPDATE`(+`imported_at = now()`) |
| | `iter_all(batch_size=2000)` | `Iterator[SourceDocument]` — 서버 쪽 이름 있는 커서로 흘려 보냄(4만 건 메모리 적재 없음), doc_id 순 |
| | `count()` | `int` |
| `PgChunkRepository(conn)` | `replace_for_version(index_version, chunks)` | `int` — 같은 판본 DELETE 후 INSERT, 다른 판본 청크가 섞이면 `ValueError` |
| | `list_for_version(index_version)` | `list[Chunk]` (doc_id, seq 순) |
| | `get_many(index_version, chunk_ids)` | `list[Chunk]` — 요청 순서 유지, 없는 ID 생략 |
| | `count(index_version)` | `int` (설계 외 추가) |
| `PgIndexVersionRepository(conn)` | `save(version)` | `None` — 같은 id면 갱신(미완료 판본 재생성) |
| | `get(index_version)` | `IndexVersion \| None` |
| | `mark_complete(index_version, chunk_count, skipped)` | `None` — `complete = (skipped == 0)` |
| | `latest_complete()` | `IndexVersion \| None` (설계 외 추가: `eval freeze --stage final`의 색인 판본) |
| `PgImportIssueRepository(conn)` | `add_many(issues, corpus_version)` / `count(corpus_version)` / `delete_for(corpus_version)` | CR-007 |
| | `list_for(corpus_version)` | `list[ImportIssue]` (설계 외 추가: 가져오기 보고·시험용) |
- 모든 저장소는 커밋하지 않는다(`commit` 호출 0, 확인 명령 §검증). 행·커서는 모듈 밖으로 나가지 않고 도메인 객체로 바꿔 돌려준다.
- 시험 데이터(03-db-schema §8): `tests/fixtures/raw/prec/`(실제 수집 판례 4건 발췌 + 지시문 판례 `900001`(AC-09-7) + 형사 판례 `900002`(OUT_OF_SCOPE), `판례내용`은 생략), `tests/fixtures/raw/law/민법.txt`(실제 `민법.txt`에서 규칙별 줄 발췌: 조문 9·삭제 1·제목 5), `law/상법.txt`(무시 대상), `tests/fixtures/raw/broken/prec/`(사건번호 없음·날짜 오류·JSON 깨짐).

#### 인프라 확인 포인트
- 스키마 변경 없음(TKT-DB-M1-01 `schema.sql` 그대로, CR-007 반영 상태).
- 시험은 Docker DB의 `lawqa_test`(`DATABASE_URL_TEST`)에서 시험마다 rollback.

#### 다음 단계(BE)가 쓸 것 (TKT-BE-M2-02)
- `ImportService`: `with conn.transaction():` 안에서 `PgSourceDocumentRepository.upsert_many`(묶음 단위), `PgImportIssueRepository.delete_for(corpus_version)` 후 `add_many`.
- `IndexService`: `PgIndexVersionRepository.save` → `PgChunkRepository.replace_for_version` → (PGVector 적재) → `mark_complete(skipped = PgImportIssueRepository.count(corpus_version))`.
- `eval freeze --stage final`: `PgIndexVersionRepository.latest_complete()`로 임시 코드(`cli._complete_index_version`)를 바꾼다.

#### 구현 중 자율 결정
##### TKT-DB-M2-01 원문 전체 읽기 방식
- 결정: `iter_all`은 이름 있는 서버 쪽 커서(`itersize=2000`)로 흘려 보냄 — 판례 4만 건(NFR-06)
- 선택지: **A. 서버 쪽 커서 (권장·채택)** / B. `fetchall`
- 권장 이유: 색인할 때 원문 전체(수백 MB 가능)를 한꺼번에 메모리에 올리지 않는다.
- trade-off: A — 커서가 트랜잭션 안에서만 살아 있음(호출하는 쪽이 다 읽고 끝내야 함). B — 메모리 사용 큼.

#### 설계와 다르게 한 것 / 질문
- 설계(§7) 밖 메서드 추가: `PgChunkRepository.count`, `PgIndexVersionRepository.latest_complete`, `PgImportIssueRepository.list_for` — 이유는 표 참고. → ARCH에 §7 목록 추가 요청.
- CR-007(승인)대로 `PgImportIssueRepository`는 `corpus_version`을 받는다(§7 원문은 `index_version`).

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-04b | `uv run pytest tests/integration -q` | 38 passed(이번 티켓 9개) |
| GATE-04 | `uv run pytest tests/unit -q` | 132 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-08 | `application`·`domain`의 저장 계층 import | 0줄 |
| 커밋 위치 | `git grep --untracked -nE "\.commit\(" -- "src/lawqa/corpus/infrastructure/"` | 0줄 |

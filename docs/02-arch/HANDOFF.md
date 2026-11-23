# HANDOFF — 구현 티켓 (C1)
- 현재 사이클: C1
- 최종 확인: 확인됨 (user, 2026-11-23)

> 읽는 순서: `AGENTS.md`(디렉토리 지도) → 자기 티켓 상세의 "읽을 것"만. 이름·명령은 `04-interfaces-api.md`, 표·파일 형식은 `03-db-schema.md`, 게이트는 `06-quality-gates.md`.
> **구현 전 할 일**: CR-002(대상 PM, 승인)를 PM "CR 반영 실행"으로 반영한다. 반영 전에도 CR-002 초안이 US-05·REJ-06·AC-05-4로 쓰인다.
> 산출물 형태(프로파일 §1): 코드 + 화면 1개 + 평가 기록. 모든 단계(DB·BE·FE·QA)에 티켓이 있다. 선택 등급(M6)은 티켓 없음(요청 시 추가).

## 1. 티켓 목록

| TKT | 제목 | 담당 | 마일스톤 | 등급 | 선행 |
|---|---|---|---|---|---|
| TKT-BE-M1-01 | 프로젝트 골격(uv·설정·shared·CLI 뼈대) | BE | M1 | 필수 | — |
| TKT-DB-M1-01 | Docker DB·연결·스키마·시험 DB 픽스처 | DB | M1 | 필수 | TKT-BE-M1-01 |
| TKT-BE-M1-02 | 시작 전 점검 `check smoke`·`db init` 연결 | BE | M1 | 필수 | TKT-BE-M1-01, TKT-DB-M1-01 |
| TKT-BE-M1-03 | evaluation 도메인(평가셋·성공 기준·고정) | BE | M1 | 필수 | TKT-BE-M1-01 |
| TKT-DB-M1-02 | 평가 파일 저장소(평가셋 로더·RunStore) | DB | M1 | 필수 | TKT-DB-M1-01, TKT-BE-M1-03 |
| TKT-BE-M1-04 | 고정 서비스·`eval freeze` | BE | M1 | 필수 | TKT-DB-M1-02 |
| TKT-BE-M2-01 | corpus 도메인·청킹·Kiwi·JSONL 읽기 | BE | M2 | 필수 | TKT-BE-M1-01 |
| TKT-DB-M2-01 | 원문·청크·판본·이슈 저장소 | DB | M2 | 필수 | TKT-DB-M1-01, TKT-BE-M2-01 |
| TKT-DB-M2-02 | PGVector 색인 어댑터 | DB | M2 | 필수 | TKT-DB-M2-01 |
| TKT-BE-M2-02 | 가져오기·색인 서비스·`corpus import/index` | BE | M2 | 필수 | TKT-DB-M2-02 |
| TKT-BE-M2-03 | retrieval 도메인(ExamItem·분해·결과 합침) | BE | M2 | 필수 | TKT-BE-M1-01 |
| TKT-BE-M2-04 | 검색 구성 A·B(PGVector·BM25·Ensemble) | BE | M2 | 필수 | TKT-BE-M2-02, TKT-BE-M2-03 |
| TKT-BE-M3-01 | 검색 구성 C(CrossEncoderReranker) | BE | M3 | 필수 | TKT-BE-M2-04 |
| TKT-BE-M3-02 | answering 도메인(Answer 규칙) | BE | M3 | 필수 | TKT-BE-M1-01 |
| TKT-BE-M3-03 | 생성·AnswerService·`ask` | BE | M3 | 필수 | TKT-BE-M3-01, TKT-BE-M3-02 |
| TKT-BE-M3-04 | 쿼리 리라이트·구성 C+R | BE | M3 | 필수 | TKT-BE-M3-03 |
| TKT-BE-M3-05 | 평가 실행 `eval run`(검사·기록·이어 하기) | BE | M3 | 필수 | TKT-DB-M1-02, TKT-BE-M3-03 |
| TKT-FE-M3-01 | Streamlit 문항 풀이 화면(PAGE-01) | FE | M3 | 필수 | TKT-BE-M3-04 |
| TKT-QA-M3-01 | M1~M3 수용 시험 | QA | M3 | 필수 | TKT-FE-M3-01, TKT-BE-M3-05 |
| TKT-BE-M4-01 | LLM 채점·사람 검토 가져오기 | BE | M4 | 필수 | TKT-BE-M3-05 |
| TKT-BE-M4-02 | 지표 계산 `eval metrics` | BE | M4 | 필수 | TKT-BE-M4-01 |
| TKT-QA-M4-01 | 본 평가 기록·지표 검증 | QA | M4 | 필수 | TKT-BE-M4-02 |
| TKT-FE-M5-01 | README | FE | M5 | 필수 | TKT-QA-M4-01 |
| TKT-QA-M5-01 | 재현·제출 점검 | QA | M5 | 필수 | TKT-FE-M5-01 |

마일스톤별: M1 6개, M2 6개, M3 7개, M4 3개, M5 2개 = 24개.

## 2. 티켓 상세

**TKT-BE-M1-01: 프로젝트 골격**
- 읽을 것: AGENTS.md, ADR-003, ADR-005, 02-system-architecture §2, 04-interfaces-api §1.1·§3·§6·§11, 05-structure-conventions §1·§4·§6·§7·§8
- 산출: `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `.env.example`, `config/base.toml`, `config/{A,B,C,C+R}.toml`, `data/raw/.gitkeep`, `src/lawqa/__init__.py`, `src/lawqa/__main__.py`, `src/lawqa/shared/{__init__,clock,settings,versioning,logging_setup}.py`, `src/lawqa/entrypoints/{__init__,cli}.py`(명령 그룹 뼈대, 아직 동작 없는 명령은 "미구현" 종료 코드 1), 각 모듈 패키지 `__init__.py`, `tests/unit/shared/test_settings.py`, `docs/04-backend/briefing.md`
- 완료 조건: GATE-01(db init 제외: `--help`), GATE-03, GATE-04, GATE-05, GATE-06. `Settings.config_sha`가 구성 파일이 바뀌면 바뀜. PyTorch는 S-05대로 CUDA 인덱스 지정
- 하지 말 것: 허용 목록 밖 패키지 추가, 비밀값 기본값

**TKT-DB-M1-01: Docker DB·연결·스키마**
- 읽을 것: AGENTS.md, ADR-006, 03-db-schema §2·§3, 04-interfaces-api §10, 05-structure-conventions §8, 06-quality-gates GATE-01·04b
- 산출: `compose.yaml`(서비스 `db`, `pgvector/pgvector:pg17`, `${POSTGRES_PASSWORD}`, 볼륨 `lawqa_pgdata`, `lawqa`·`lawqa_test` DB 생성 초기화), `src/lawqa/shared/db.py`(`connect(url) -> psycopg.Connection`, `init_schema(conn) -> None`), `src/lawqa/corpus/infrastructure/schema.sql`, `tests/conftest.py`(`db_conn` 픽스처: `DATABASE_URL_TEST`로 연결·스키마 재생성), `tests/integration/db/test_schema.py`, `docs/03-db/briefing.md`
- 완료 조건: `init_schema`가 빈 DB에 두 번 실행해도 오류 없음, GATE-04b, CHECK 제약 시험(판례 본문 없음 거부). `db init` 명령 연결은 TKT-BE-M1-02
- 하지 말 것: ORM 도입, PGVector 표를 schema.sql에 정의

**TKT-BE-M1-02: 시작 전 점검 `check smoke`·`db init` 연결**
- 읽을 것: AGENTS.md, ADR-008, ADR-010, 04-interfaces-api §3 API-04, 05-structure-conventions §6 S-05·S-06
- 산출: `src/lawqa/entrypoints/cli.py`(check smoke, db init → `shared.db.init_schema`), `src/lawqa/shared/smoke.py`(점검 함수, 결과를 `results/smoke/<날짜>.json`에 기록), `tests/unit/shared/test_smoke.py`(대역), `docs/04-backend/briefing.md`
- 완료 조건: AC-03-1, AC-03-2(BM25·벡터 시험 출력은 `tests/fixtures/raw` 문서 3개로 메모리 검색), GPU 장치 이름·재정렬 1건 지연 출력, GATE-01 전체, GATE-04·05
- 하지 말 것: 결과에 API 키 기록

**TKT-BE-M1-03: evaluation 도메인**
- 읽을 것: AGENTS.md, ADR-014, 03-db-schema §5, 04-interfaces-api §1.5·§1.6
- 산출: `src/lawqa/evaluation/domain/{models,run,metrics,errors,ports}.py`(`Metrics`는 시그니처와 Hit@5 계산까지, 나머지는 TKT-BE-M4-02), `tests/unit/evaluation/test_evalset.py`, `test_run_rules.py`, `test_freeze.py`, `tests/fixtures/eval/{dev,test}.json`(가짜 내용, 형식만 맞음), `docs/04-backend/briefing.md`
- 완료 조건: INV-05·06·12 단위 시험(AC-04-1·3, AC-12-2·3의 도메인 부분), GATE-02·04·07
- 하지 말 것: 파일 읽기 코드(그건 DB 티켓)

**TKT-DB-M1-02: 평가 파일 저장소**
- 읽을 것: AGENTS.md, ADR-006, ADR-014, 03-db-schema §5·§7
- 산출: `src/lawqa/evaluation/infrastructure/files.py`(`JsonEvalSetRepository`, `SuccessCriteriaFile`, `FreezeFile`, `RunStore`: append 즉시 flush, 기존 줄 수정 없음), `tests/integration/db/test_eval_files.py`(tmp_path), `docs/03-db/briefing.md`
- 완료 조건: 기록 중단 후 다시 열어도 기존 줄 유지, `RunStore.append`가 줄 단위 JSON, GATE-04b·08
- 하지 말 것: `results/` 기존 줄 덮어쓰기

**TKT-BE-M1-04: 고정 서비스·`eval freeze`**
- 읽을 것: AGENTS.md, ADR-014, 04-interfaces-api §2·§3 API-06·SEQ-06·§9.3
- 산출: `src/lawqa/evaluation/application/freeze_service.py`, cli.py(eval freeze), `tests/unit/evaluation/test_freeze_service.py`, `docs/04-backend/briefing.md`
- 완료 조건: AC-02-1·2(파일·고정 커밋 순서 검사 기능), `final` 재고정 거부, 커밋 안 된 변경 있으면 거부, GATE-04
- 하지 말 것: git 태그 생성(사람이 함)

**TKT-BE-M2-01: corpus 도메인·청킹**
- 읽을 것: AGENTS.md, ADR-007, 03-db-schema §3·§4·§8, 04-interfaces-api §1.2
- 산출: `src/lawqa/corpus/domain/{models,chunking,errors,ports}.py`, `src/lawqa/corpus/infrastructure/{jsonl_reader,kiwi_tokenizer}.py`, `tests/unit/corpus/test_source_document.py`, `test_chunking.py`, `test_jsonl_reader.py`, `docs/04-backend/briefing.md`
- 완료 조건: 판시사항·판결요지 `[n]` 묶음, 번호 없음, 조문 항 분할, `location` 형식(03-db-schema §4 예와 같음), 형식 오류 줄 → `ImportIssue`(AC-05-4 도메인 부분), GATE-02·04
- 하지 말 것: DB 코드

**TKT-DB-M2-01: 원문·청크·판본·이슈 저장소**
- 읽을 것: AGENTS.md, ADR-006, 03-db-schema §3·§7, 04-interfaces-api §10
- 산출: `src/lawqa/corpus/infrastructure/{pg_documents,pg_chunks,pg_index}.py`, `tests/integration/db/test_corpus_repositories.py`, `tests/fixtures/raw/{precedents_sample,statutes_sample,broken}.jsonl`, `docs/03-db/briefing.md`
- 완료 조건: upsert 멱등, `replace_for_version` 교체, 행 → 도메인 변환, GATE-04b·08, AC-05-3(같은 입력 두 번 → 같은 청크 ID 집합)
- 하지 말 것: 커밋을 저장소 안에서 호출

**TKT-DB-M2-02: PGVector 색인 어댑터**
- 읽을 것: AGENTS.md, ADR-009, 03-db-schema §3(ENT-05)·§7, 05-structure-conventions §6 S-03
- 산출: `src/lawqa/corpus/infrastructure/vector_index.py`(`PgVectorIndex`), `tests/integration/db/test_vector_index.py`(`DeterministicFakeEmbedding`), `docs/03-db/briefing.md`
- 완료 조건: 컬렉션 이름·문서 ID·메타데이터 규칙, `count == 청크 수`(GATE-10 근거), GATE-04b
- 하지 말 것: 우리 schema.sql에 벡터 표 추가

**TKT-BE-M2-02: 가져오기·색인 서비스**
- 읽을 것: AGENTS.md, ADR-007, 04-interfaces-api §2·§3 API-02·03·SEQ-01·02·§9.2, CR-002(change-requests.md)
- 산출: `src/lawqa/corpus/application/{import_service,index_service,chunk_query_service}.py`, `src/lawqa/corpus/infrastructure/__init__.py`(`build_*`), cli.py(corpus import/index), `tests/unit/corpus/test_index_service.py`(가짜 저장소), `docs/04-backend/briefing.md`
- 완료 조건: AC-05-1·2·4, GATE-10 출력 형식, 재실행 시 같은 판본 "이미 있음", GATE-04
- 하지 말 것: 수집(HTTP) 코드

**TKT-BE-M2-03: retrieval 도메인**
- 읽을 것: AGENTS.md, ADR-011, 04-interfaces-api §1.3·§1.6
- 산출: `src/lawqa/retrieval/domain/{models,decomposer,errors,ports}.py`, `tests/unit/retrieval/test_exam_item.py`, `test_decomposer.py`, `test_question_list.py`, `docs/04-backend/briefing.md`
- 완료 조건: R-3 입력 검증(AC-09-4 도메인 부분), 라운드로빈 합침·중복 제거, `RetrievalConfig.comparable_key`(INV-08), GATE-02·04
- 하지 말 것: LangChain import

**TKT-BE-M2-04: 검색 구성 A·B**
- 읽을 것: AGENTS.md, ADR-009, ADR-011, 04-interfaces-api §1.3·SEQ-03, 05-structure-conventions §6 S-01·S-02
- 산출: `src/lawqa/retrieval/infrastructure/retrievers.py`(A: PGVector 검색기, B: BM25(Kiwi)+Ensemble, 기록용 개별 순위·점수 → `Candidate`), `src/lawqa/retrieval/application/retrieval_service.py`(A·B), `tests/unit/retrieval/test_retrieval_service.py`(가짜 검색기, 실제 DB 연동 확인은 `check smoke`), `docs/04-backend/briefing.md`
- 완료 조건: AC-06-1, AC-07-1·2, GATE-02·04·08
- 하지 말 것: 점수 단순 합산

**TKT-BE-M3-01: 검색 구성 C**
- 읽을 것: AGENTS.md, ADR-010, 04-interfaces-api SEQ-03, 05-structure-conventions §6 S-04·S-05·S-10
- 산출: `src/lawqa/retrieval/infrastructure/reranker.py`, retrieval_service.py(C), `tests/unit/retrieval/test_rerank_order.py`(가짜 점수), `docs/04-backend/briefing.md`
- 완료 조건: AC-08-1·2, `reranker_device` 설정 반영, GATE-04
- 하지 말 것: LLM 재정렬

**TKT-BE-M3-02: answering 도메인**
- 읽을 것: AGENTS.md, ADR-004, ADR-013, 04-interfaces-api §1.4·§4·§9.1, 03-domain §7(R-2)
- 산출: `src/lawqa/answering/domain/{models,errors,ports}.py`, `tests/unit/answering/test_answer_rules.py`, `docs/04-backend/briefing.md`
- 완료 조건: INV-01·03·13 단위 시험(후보 밖 인용 제거, 정답 보기 인용 0 → 근거 부족, 오류 결과 번호 없음), GATE-02·04
- 하지 말 것: 모델 호출

**TKT-BE-M3-03: 생성·AnswerService·`ask`**
- 읽을 것: AGENTS.md, ADR-004, ADR-013, 04-interfaces-api §2·§3 API-05·§4·§5.1·§10·SEQ-03, 05-structure-conventions §6 S-06
- 산출: `src/lawqa/answering/infrastructure/{generator.py,prompts/answer.txt,__init__.py}`, `src/lawqa/answering/application/answer_service.py`, cli.py(ask), `tests/unit/answering/test_answer_service.py`(대역: 검색 실패·모델 실패·형식 오류·정상), `docs/04-backend/briefing.md`
- 완료 조건: AC-09-1·2·3·5·6·8의 서비스 수준 시험(대역), 모든 예외가 `Answer`로, GATE-04·07
- 하지 말 것: 프롬프트를 코드 문자열로

**TKT-BE-M3-04: 쿼리 리라이트·C+R**
- 읽을 것: AGENTS.md, D-005(decision-log), 04-interfaces-api §5.2·SEQ-03, ADR-011
- 산출: `src/lawqa/retrieval/infrastructure/{rewriter.py,prompts/rewrite.txt}`, retrieval_service.py(리라이트 단계), `tests/unit/retrieval/test_rewrite_fallback.py`, `docs/04-backend/briefing.md`
- 완료 조건: AC-10-1·2·3, INV-10, GATE-04·09
- 하지 말 것: 리라이터 입력에 평가 데이터

**TKT-BE-M3-05: 평가 실행 `eval run`**
- 읽을 것: AGENTS.md, ADR-014, 03-db-schema §5, 04-interfaces-api §2·§3 API-07·SEQ-04, 03-domain §7(R-1)
- 산출: `src/lawqa/evaluation/application/run_service.py`, cli.py(eval run, `--resume`, `--dry-run`, `--only`), `tests/unit/evaluation/test_run_service.py`(대역 AnswerService), `docs/04-backend/briefing.md`
- 완료 조건: AC-12-1·2·3, AC-13-1·2·3·4(대역), 중단 후 `--resume`, GATE-04·11
- 하지 말 것: 실패 기록 삭제·덮어쓰기

**TKT-FE-M3-01: Streamlit 화면**
- 읽을 것: AGENTS.md, 07-screens.md#SCR-01, 04-interfaces-api.md#PAGE-01(§7)·§4, docs/04-backend/briefing.md
- 산출: `src/lawqa/entrypoints/streamlit_app.py`, `tests/unit/entrypoints/test_streamlit_app.py`(Streamlit `AppTest`, 대역 AnswerService), `docs/05-frontend/briefing-TKT-FE-M3-01.md`
- 완료 조건: AC-11-1·2·3, 상태 6종 표시, GATE-04·05
- 하지 말 것: 화면에서 결과 판정·인용 검증(도메인 몫)

**TKT-QA-M3-01: M1~M3 수용 시험**
- 읽을 것: 06-acceptance-criteria.md#AC-01~AC-12, 06-quality-gates.md, docs/03-db/briefing.md, docs/04-backend/briefing.md, docs/05-frontend/briefing-TKT-FE-M3-01.md
- 산출: `tests/acceptance/test_ac_03_*.py`~`test_ac_12_*.py`(파일·문서 AC는 존재·필드 검사), `docs/06-qa/briefing-TKT-QA-M3-01.md`
- 완료 조건: GATE 전체, AC-09-7 지시문 시험(`live` 표시 1건 + 대역 1건)

**TKT-BE-M4-01: 채점**
- 읽을 것: AGENTS.md, ADR-014, D-006, 04-interfaces-api §2·§3 API-08·09·§5.3·SEQ-05
- 산출: `src/lawqa/evaluation/infrastructure/{judge.py,prompts/judge.txt}`, `src/lawqa/evaluation/application/grading_service.py`, cli.py(eval grade/review), `tests/unit/evaluation/test_grading.py`, `docs/04-backend/briefing.md`
- 완료 조건: AC-14-1, AC-14-3, review.csv 형식 검증, GATE-04·09(judge만 정답 접근)

**TKT-BE-M4-02: 지표**
- 읽을 것: AGENTS.md, 04-interfaces-api §1.5(Metrics)·API-10, 06-acceptance-criteria NFR-01~03·05
- 산출: `src/lawqa/evaluation/domain/metrics.py`(완성), `src/lawqa/evaluation/application/metrics_service.py`, cli.py(eval metrics), `tests/unit/evaluation/test_metrics.py`, `docs/04-backend/briefing.md`
- 완료 조건: AC-14-2·4(분모 17·3, 검색 실패 0, 5개 미만 처리), 사람 판정 기준 + LLM 일치율, GATE-04

**TKT-QA-M4-01: 본 평가 기록·지표 검증**
- 읽을 것: 06-acceptance-criteria.md#AC-13~AC-15, NFR-01~05, 06-quality-gates.md, docs/04-backend/briefing.md
- 산출: `tests/acceptance/test_ac_13_*.py`~`test_ac_15_*.py`(실제 `results/` 기록 검사: 80건·필드·분모·종류 표시), `docs/06-qa/briefing-TKT-QA-M4-01.md`
- 완료 조건: 기록 80건 필드 완결(NFR-05), report 분모 = 기록 수(AC-15-2)

**TKT-FE-M5-01: README**
- 읽을 것: AGENTS.md, 05-structure-conventions §1·§2, 04-interfaces-api §3, 06-quality-gates GATE-01, docs/06-qa/briefing-TKT-QA-M4-01.md
- 산출: `README.md`, `docs/05-frontend/briefing-TKT-FE-M5-01.md`
- 목차(IC-15): 1. 소개(문제·범위, "작은 평가셋 검증" 문장, C-12) 2. 구조도(05 §2 원본) 3. 준비물(uv, Docker Desktop, OpenAI 키, GPU 선택) 4. 설치(`uv sync`, `.env`, `docker compose up -d db`, `db init`) 5. 데이터 준비(`data/raw` 형식 ADR-007, `data/MANIFEST.md`) 6. 색인(`corpus import`, `corpus index`) 7. 실행(`ask`, Streamlit) 8. 평가 재현(`eval freeze/run/grade/review/metrics`, 결과 위치) 9. 대표 사례 재실행(정상 1·근거 없음 1) 10. 한계와 데이터 이용 조건
- 완료 조건: AC-16-1을 README 명령만으로 수행 가능(QA-M5-01이 확인)

**TKT-QA-M5-01: 재현·제출 점검**
- 읽을 것: 06-acceptance-criteria.md#AC-16·AC-17, 06-quality-gates GATE-06, README.md
- 산출: `tests/acceptance/test_ac_17_*.py`(비밀값·필수 파일·report 문장), `results/repro/<날짜>/`(별도 세션 재실행 기록), `docs/06-qa/briefing-TKT-QA-M5-01.md`
- 완료 조건: AC-16-1·2(새 클론·새 가상환경의 별도 세션, D-006), AC-17-1·2·3

## 3. 사람이 할 일 (티켓 아님)
| 시점 | 할 일 | 근거 |
|---|---|---|
| M1 전 | `data/raw/precedents/*.jsonl`, `data/raw/statutes/*.jsonl` 준비(ADR-007 형식), `data/MANIFEST.md` 작성 | ADR-007, CR-002 |
| M1 | `docs/problem.md`, `eval/success_criteria.json`(D-007) → `eval freeze --stage criteria` → 커밋·태그 `freeze-criteria` | US-01·02 |
| M1 | `eval/SCHEMA.md`, `eval/dev.json`·`test.json` 30문항(DOC-04·05) | US-04 |
| M3 끝 | dev로 설정 확정 → `eval freeze --stage final` → 커밋·태그 `freeze-final` | US-12 |
| M4 | 본 평가 `eval run`(A·B·C·C+R, test, main), `eval grade`, `review.csv` 사람 판정, `eval review`, `eval metrics` | US-13·14 |
| M4~M5 | `report.md`, `contributions.md`, 발표·시연, 태그 `ax1-project3-submit` | US-15·17 |

## 4. 추적 갱신 결과 (AQ)
| AQ | 답한 위치 |
|---|---|
| AQ-001 | ADR-008(임베딩 small), ADR-009(PGVector·BM25), ADR-010(bge-reranker) |
| AQ-002 | ADR-012(Streamlit), PAGE-01 |
| AQ-003 | ADR-011, 04-interfaces-api §6 `[retrieval]` |
| AQ-004 | 03-db-schema §4 |
| AQ-005 | ADR-013, 04-interfaces-api §1.4 |
| AQ-006 | 04-interfaces-api §5.1 |
| AQ-007 | 03-db-schema §4 `location` |
| AQ-008 | 04-interfaces-api §10, 06-quality-gates §3 |
| AQ-009 | ADR-006, 05-structure-conventions §1·§7 |
| AQ-010 | ADR-003, ADR-007(OPEN API 인증 값 불필요), 05 §8 |
| AQ-011 | 03-db-schema §5 |
| AQ-012 | ADR-014, SEQ-06, §9.3 |
| AQ-013 | 04-interfaces-api §5.2, SEQ-03 |
| AQ-014 | ADR-007(별도 수집, 사용자 지시) |
| AQ-015 | ADR-011 |

## 5. 구현 계약 체크리스트 (A8-1)
| # | 항목 | 위치 |
|---|---|---|
| IC-01 | 단계별 쓰는 경로, 공통 파일 담당 | AGENTS.md 디렉토리 지도 |
| IC-02 | 테스트 담당·위치, 티켓 산출에 시험 경로 | 06-quality-gates §2, 이 문서 §2 |
| IC-03 | 스택·버전, 트리, import 규칙 | 02-system-architecture §2, 05 §1·§3 |
| IC-04 | 의존 방향, 금지 패턴 | 05 §3·§5 |
| IC-05 | 명명(클래스·파일·표·제약·시험) | 05 §4, 03-db-schema §3 |
| IC-06 | 에러 모델·결과 종류·종료 코드, 비HTTP 인터페이스 명세(CLI) | 04-interfaces-api §3·§4 |
| IC-07 | 트랜잭션 경계, 연결 수명, 저장 모델 노출 경계 | 04 §10, 03 §7 |
| IC-08 | psycopg 3 동기, `schema.sql` IF NOT EXISTS, 기존 DB 처리 | ADR-006, 03 §3 |
| IC-09 | 인증: 해당 없음(ADR-002). 비밀값·설정 경로, 비노출 필드 | ADR-003, 05 §8, 04 §11 |
| IC-10 | Streamlit(ADR-012), PAGE-01, 스타일 기본 테마(UX 없음) | 04 §7 |
| IC-11 | 실행·검증 명령과 기준, 시험 DB(`lawqa_test`), Docker 준비 | 06-quality-gates §1, ADR-005·006 |
| IC-12 | 스택 주의 S-01~S-10(출처·미확인 표시) | 05 §6 |
| IC-13 | 시드: 시험 고정 데이터·중복 방지 | 03-db-schema §8 |
| IC-14 | 범위 등급: 모든 티켓 필수, 선택 등급은 티켓 없음(요청 시 추가). 임시 코드: `check smoke`의 메모리 검색은 시험용으로 유지(제거 티켓 없음) | 이 문서 §1 |
| IC-15 | README 목차 | TKT-FE-M5-01 |

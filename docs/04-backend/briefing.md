---
stage: BE
tickets: [TKT-BE-M1-01, TKT-BE-M1-02, TKT-BE-M1-03, TKT-BE-M1-04, TKT-BE-M2-01, TKT-BE-M2-02, TKT-BE-M2-03, TKT-BE-M2-04, TKT-BE-M3-01, TKT-BE-M3-02, TKT-BE-M3-03, TKT-BE-M3-04, TKT-BE-M3-05]
status: done
inputs_read: [AR-MAP, AR-HAND, AR-API, AR-CONV, AR-GATE, DB-BRIEF, CR-LOG]
next_readers: [DB, FE, QA]
---
# 백엔드 에이전트 브리핑

## 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M1-01 | GATE-01(`--help`), GATE-03, GATE-04, GATE-05, GATE-06 | 충족 | §검증 결과의 명령 실행 |
| TKT-BE-M1-01 | `Settings.config_sha`가 구성 파일이 바뀌면 바뀜 | 충족 | `test_config_sha_changes_when_run_config_file_changes`, `..._base_file_changes` |
| TKT-BE-M1-01 | PyTorch는 S-05대로 CUDA 인덱스 지정 | 충족 | `uv.lock`의 `torch 2.11.0+cu128`(인덱스 `download.pytorch.org/whl/cu128`) |

### TKT-BE-M1-01

## 만든 것
- 명령줄(API 뼈대): `python -m lawqa <group> <command>` — `db init`, `corpus import|index`, `check smoke`, `ask`, `eval freeze|run|grade|review|metrics`의 인자를 04-interfaces-api §3대로 정의. 아직 구현되지 않은 명령은 `미구현: … 명령은 <TKT>에서 구현합니다.`를 stderr로 내고 종료 코드 1. 화면 라우트 없음(Streamlit은 FE).
- 설정 `lawqa.shared.settings`
  - `load_settings(config_name="base", *, config_dir=Path("config"), env_file=Path(".env"), environ=None) -> Settings`
  - `Settings`(frozen): `config_name`, `config_sha`, `models`, `chunking`, `retrieval`, `timeouts`, `paths`, `run`, `secrets`
  - 구성 파일(`A`·`B`·`C`·`C+R`)은 `[run]`만 덮어쓸 수 있음 — 다른 절이 있으면 `SettingsError`(INV-08을 파일 구조로 보장)
  - `config_sha` = `base.toml`과 구성 파일의 (이름, 내용) 해시(`sha256_of_files`)
  - `Secrets.require(name)`: 비어 있으면 이름만 담은 `SettingsError`, `repr`에 값 없음
- `lawqa.shared.versioning`: `sha256_of(bytes)`, `sha256_of_files(paths)` (표준 라이브러리만)
- `lawqa.shared.clock`: `Clock` Protocol, `SystemClock.now()`(로컬 시간대 포함)
- `lawqa.shared.logging_setup`: `configure_logging(level)`, `format_event(event, **fields)`, `log_event(logger, event, level, **fields)` — 한 줄 `ts level module event=… key=value`
- 패키지 골격: `corpus`·`retrieval`·`answering`·`evaluation` 각각 `domain`/`application`/`infrastructure` 패키지(빈 `__init__.py`와 책임 설명)
- 설정·환경: `pyproject.toml`(Python `>=3.12,<3.13`, 의존성은 02-system-architecture §2 스택표대로), `uv.lock`(145개), `.python-version`(3.12), `config/base.toml`·`A`·`B`·`C`·`C+R.toml`, `.env.example`, `.gitignore`(`data/*` 제외·`!data/MANIFEST.md`, `.streamlit/secrets.toml` 추가)
- 시험: `tests/unit/shared/test_settings.py`(15개)

고정된 주요 버전(`uv.lock`): langchain 1.5.2, langchain-core 1.8.4, langchain-openai 1.8.5, langchain-community 0.4.2, langchain-classic 1.0.8, langchain-postgres 0.0.19, psycopg 3.3.9, kiwipiepy 0.25.1, rank-bm25 0.2.2, sentence-transformers 6.3.0, torch 2.11.0+cu128, streamlit 1.67.0, pytest 9.2.0, ruff 0.17.6, python-dotenv 1.2.4.

## 계층 확인 포인트
- 도메인 패키지는 비어 있음(외부 import 0, GATE-02 통과). 모듈 간 의존 없음(GATE-02b 통과).
- `os.environ`을 읽는 곳은 `shared/settings.py`뿐(CONV-10). 저장소 모델·트랜잭션은 아직 없음.

## 보안 확인 포인트
- 비밀값 3종(`OPENAI_API_KEY`, `DATABASE_URL`, `DATABASE_URL_TEST`)은 `.env`·환경변수에서만 읽고 `Settings` `repr`에 나오지 않음(시험으로 확인). `POSTGRES_PASSWORD`는 compose 전용이라 설정 객체에 넣지 않음.
- `.env*`는 기존 `.gitignore`가 제외(`!.env.example`만 허용). `.env.example`에는 이름과 용도만.

## 임시 코드
- 명령줄의 "미구현" 분기(`_PENDING_TICKETS`): 각 명령을 구현하는 티켓에서 해당 항목을 지운다. 마지막은 TKT-BE-M4-02. 모두 지우면 `_PENDING_TICKETS`와 "알 수 없는 명령" 분기를 함께 정리한다.

## 프론트엔드에게 전달할 것
- 설정은 `from lawqa.shared.settings import load_settings`로 읽는다(화면 구성 선택값 `A`·`B`·`C`·`C+R`은 `RUN_CONFIGS`). `AnswerService`는 TKT-BE-M3-03에서 제공.

## 구현 중 자율 결정
#### TKT-BE-M1-01 빌드 백엔드
- 결정: `uv_build`(src 레이아웃, 모듈 `lawqa`) — ADR-005(uv)
- 선택지: **A. uv_build (권장·채택)** / B. hatchling / C. 빌드 없이 `PYTHONPATH=src`
- 권장 이유: uv 하나로 설치·잠금·빌드가 끝나고 추가 도구가 없다.
- trade-off: A — uv 버전 범위(`>=0.12,<0.13`)를 맞춰야 함. B — 빌드 도구 하나 추가. C — `python -m lawqa`가 환경 설정에 의존.

#### TKT-BE-M1-01 `base.toml`의 `[run]` 기본값
- 결정: `base.toml`에 `[run] mode="C", use_rewrite=false`를 두고 구성 파일이 덮어씀 — 04-interfaces-api §6
- 선택지: **A. base에 기본값 (권장·채택)** / B. `[run]` 없이 구성 파일 필수
- 권장 이유: `corpus index --config base`처럼 구성이 필요 없는 명령도 같은 `Settings`를 쓸 수 있다.
- trade-off: A — base만으로 답변을 실행하면 C 구성이 쓰임(본 평가는 구성 이름이 기록되므로 구분됨). B — 구성 없는 명령마다 가짜 구성이 필요.

#### TKT-BE-M1-01 구성 파일 검사 강도
- 결정: 구성 파일에 `[run]` 외 절이 있으면 거부 — INV-08
- 선택지: **A. 거부 (권장·채택)** / B. 경고만
- 권장 이유: A/B/C/C+R 비교에서 모델·프롬프트·검색 값이 몰래 달라지는 것을 막는다.
- trade-off: A — 구성별로 다른 값을 실험하려면 base를 바꾸고 추가 실험으로 분리해야 함. B — 비교 공정성을 코드로 보장하지 못함.

#### TKT-BE-M1-01 명령줄 UTF-8 출력
- 결정: `main()` 시작에서 stdout·stderr를 UTF-8로 재설정 — 실행 중 Windows 콘솔(cp949)에서 한글 메시지가 깨짐을 확인
- 선택지: **A. 진입점에서 재설정 (권장·채택)** / B. 사용자에게 `PYTHONUTF8=1` 안내
- 권장 이유: README 명령만으로 재현해야 하므로(C-14) 환경 설정에 기대지 않는다.
- trade-off: A — 출력 인코딩을 코드가 강제. B — 사용자마다 설정 필요.

## 설계와 다르게 한 것 / 질문 / DB 에이전트에게 요청
- 설계와 다르게 한 것: 없음.
- **ARCH에 알림(CR 후보)**: `06-quality-gates.md` 게이트 표의 정규식은 마크다운 표 때문에 `\|`로 적혀 있다. 실제 실행은 `git grep -E`에 `|`를 써야 한다(이번 실행은 `|`로 했고 모두 0줄). 표 아래에 "표 안의 `\|`는 `|`로 입력" 한 줄을 더해 달라고 요청한다.
- 참고: 작업 폴더에 이전 프로젝트의 추적되지 않는 `src/{auth,rooms,bootstrap}/__pycache__`, `tests/{unit,integration}/__pycache__`가 남아 있다. `.gitignore` 대상이라 커밋·시험에 영향은 없다(지우지 않음).
- DB 에이전트에게: `tests/conftest.py`는 DB 담당이다. 현재 BE 시험은 conftest 없이 돈다. `DATABASE_URL_TEST`는 `Settings.secrets.database_url_test`로 읽을 수 있다.

## 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-01(`db init` 제외) | `uv sync` → `uv run python -m lawqa --help` | 종료 코드 0 (`db init`은 TKT-BE-M1-02에서 연결) |
| GATE-02 | 06-quality-gates GATE-02 명령(표의 `\|`를 `|`로 입력) | 0줄 |
| GATE-02b | 모듈 방향 4개 명령 | 각 0줄 |
| GATE-03 | `uv run python -c "import lawqa.corpus.domain, lawqa.retrieval.domain, lawqa.answering.domain, lawqa.evaluation.domain, lawqa.entrypoints.cli"` | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 15 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 모두 포맷됨 |
| GATE-06 | `git ls-files .env`, 키 패턴 `git grep`, `.gitignore`의 `.env*` | 0줄, 0줄, 있음 |
| GATE-07 | 빈 except·도메인 시각·난수 `git grep` | 각 0줄 |
| GATE-08 | `application`·`domain`의 저장 계층·LangChain import | 0줄 |
| GATE-09 | `corpus`·`retrieval`·`answering`의 정답 경로 | 0줄 |
- 확인하지 못한 것: GPU에서 PyTorch 동작(`torch.cuda.is_available()`)은 TKT-BE-M1-02 `check smoke`에서 확인한다.
- 미구현 명령 확인: `uv run python -m lawqa eval freeze --stage criteria` → `미구현: \`eval freeze\` 명령은 TKT-BE-M1-04에서 구현합니다.`, 종료 코드 1.

---

### TKT-BE-M1-02 (`check smoke`·`db init` 연결)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M1-02 | AC-03-1 생성·임베딩 각 1건의 모델명·성공 여부 | 충족 | 실측 `results/smoke/2026-11-24_092623.json`: 생성 `gpt-6-luna`(응답 모델명 `gpt-6-luna`), 임베딩 `text-embedding-3-small` 1536차원, 둘 다 `ok` |
| TKT-BE-M1-02 | AC-03-2 같은 질의의 BM25·벡터 점수를 따로 기록, 척도 설명 | 충족 | 같은 파일 `bm25`·`vector`·`score_scales`, 시험 `test_ac_03_2_…` |
| TKT-BE-M1-02 | GPU 장치 이름·재정렬 1건 지연 | 충족 | `NVIDIA GeForce RTX 5060 Laptop GPU`, `torch 2.11.0+cu128`, CUDA 사용 가능, 재정렬 3쌍 107ms(모델 적재 제외) |
| TKT-BE-M1-02 | GATE-01 전체, GATE-04·05 | 충족 | §검증 결과 |

#### 만든 것
| API | 명령 | 결과 | 종료 코드 |
|---|---|---|---|
| API-01 | `python -m lawqa db init` | `shared.db.init_schema` 호출, 완료 문구 출력 | 0 / 1(접속 문자열 없음) / 2(`psycopg.OperationalError`) |
| API-04 | `python -m lawqa check smoke` | 점검 6종 + 척도 설명, 요약 출력, 결과 파일 경로 출력 | 0(모두 성공) / 2(하나라도 실패) / 1(설정 오류) |
- `lawqa.shared.smoke`
  - `SmokeProbes` Protocol: `generation()`, `embedding()`, `gpu()`, `rerank(query, docs)`, `bm25_scores(query, docs)`, `vector_scores(query, docs)`
  - `run_smoke(settings, probes, clock) -> SmokeReport` — 점검 하나가 실패해도 나머지 계속, 실패는 `error`(예외 종류+메시지)로 기록
  - `write_report(report, results_dir, clock) -> Path` — `<results_dir>/smoke/<YYYY-MM-DD_HHMMSS>.json`, 같은 이름이 있으면 `-1`, `-2`를 붙여 덮어쓰지 않음, `sk-…` 패턴은 `sk-***`로 가림
  - `summary_lines(report) -> list[str]`
  - `LiveSmokeProbes(settings)` — ChatOpenAI·OpenAIEmbeddings(`dimensions` 지정)·torch·HuggingFaceCrossEncoder·Kiwi(내용 형태소)+`rank_bm25.BM25Okapi`. 무거운 import는 메서드 안에서.
- CLI: `_HANDLERS` 표로 구현된 명령을 연결하고, `_PENDING_TICKETS`에서 `db init`·`check smoke`를 지움.
- 시험 `tests/unit/shared/test_smoke.py` 7개(가짜 점검기).
- 실측 결과 `results/smoke/2026-11-24_092623.json`(커밋, AC-03 증빙).

#### 실측 결과 요약 (2026-11-24, 이 노트북)
| 점검 | 결과 | 지연 |
|---|---|---|
| 생성 | `gpt-6-luna` 응답 정상 | 9.1초 |
| 임베딩 | `text-embedding-3-small`, 1536차원 | 2.4초 |
| GPU | RTX 5060 Laptop, CUDA 12.8 빌드 동작 | 9.8초(torch 첫 import 포함) |
| 재정렬 | 3쌍 점수 [0.12, 0.98, 0.00], 정답 조문(제245조)이 1위 | 107ms(모델 적재 721초 = 첫 다운로드 약 2.3GB 포함) |
| BM25 | 제245조 3.12 > 제186조 0.17 > 제750조 0.00 | 1.8초(Kiwi 적재 포함) |
| 벡터 | 제245조 0.62 > 제186조 0.44 > 제750조 0.24 | 0.6초 |

#### 계층·보안 확인 포인트
- `shared.smoke`는 도메인이 아니므로 외부 라이브러리 사용 가능(GATE-02 대상 아님). 도메인·응용 패키지는 여전히 비어 있음.
- 비밀값: 키는 `Settings.secrets.require`로만 읽고 결과 파일·로그·출력에 쓰지 않음. 결과 파일의 `sk-` 문자열 0개 확인.

#### 임시 코드
- `_PENDING_TICKETS` 남은 항목: `eval freeze`(M1-04) 이후 순서대로 제거.

#### 구현 중 자율 결정
##### TKT-BE-M1-02 BM25·벡터 시험 문서
- 결정: `tests/fixtures/raw` 대신 커밋된 `law_collector/data/law/민법.txt`의 조문 3개(제186조, 제245조 제1항, 제750조)를 `SAMPLE_DOCS` 상수로 사용 — 티켓 완료 조건(AC-03-2)
- 선택지: **A. 민법 조문 3개 상수 (권장·채택)** / B. TKT-DB-M2-01 시험 데이터를 기다림
- 권장 이유: `tests/fixtures/raw`는 DB 티켓(M2)에서 만들어져 이 티켓 시점에 없다. 실제 민법 문장이라 척도 차이가 현실적으로 보인다.
- trade-off: A — 시험 문서가 코드에 들어감(3문장). B — M1 점검이 M2까지 미뤄짐.

##### TKT-BE-M1-02 점검 결과 파일 이름
- 결정: `<YYYY-MM-DD_HHMMSS>.json`(같은 이름이면 번호) — 티켓은 `<날짜>.json`
- 선택지: **A. 날짜+시각 (권장·채택)** / B. 날짜만(같은 날 덮어씀)
- 권장 이유: `results/`는 덮어쓰지 않는다(금지 패턴 13). 같은 날 여러 번 점검해도 기록이 모두 남는다.
- trade-off: A — 파일이 늘어남. B — 앞선 점검 기록이 사라짐.

##### TKT-BE-M1-02 재정렬 지연 측정 방식
- 결정: 모델 적재(`load_ms`)와 워밍업 1회를 빼고 점수 계산만 `score_ms`로 기록 — "재정렬 1건 지연"
- 선택지: **A. 적재·워밍업 분리 (권장·채택)** / B. 전체 시간
- 권장 이유: 화면·평가에서는 모델을 프로세스당 한 번 적재하므로(PAGE-01 `st.cache_resource`) 실제 응답 시간에 가까운 값이다.
- trade-off: A — 첫 실행 비용은 `load_ms`로 따로 봐야 함. B — 다운로드 시간이 지연으로 잡힘.

#### 설계와 다르게 한 것 / 질문
- 위 "BM25·벡터 시험 문서"(티켓 문구와 다름, 이유 기록).
- ARCH에 알림(스택 주의 추가 후보): Windows에서 Hugging Face 캐시가 심볼릭 링크를 못 써 경고가 나오고 캐시가 더 큰 공간을 쓴다(동작에는 문제 없음). 개발자 모드를 켜거나 `HF_HUB_DISABLE_SYMLINKS_WARNING=1`로 경고만 끌 수 있다. reranker 첫 적재가 다운로드 포함 약 12분 걸렸다.
- ARCH에 알림: 생성 1건 9.1초 — 짧은 응답에도 지연이 크다. NFR-02(중앙값 30초)에 보기 5개 처리 시간을 더하면 여유가 작을 수 있다(RISK-14). M3에서 측정한다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-01 | `docker compose up -d db` → `uv sync` → `uv run python -m lawqa db init`(두 번) → `uv run python -m lawqa --help` | 모두 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 22 passed |
| GATE-04b | `uv run pytest tests/integration -q` | 17 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| 실측 | `uv run python -m lawqa check smoke` | 6종 모두 OK, 종료 코드 0 |

---

### TKT-BE-M1-03 (evaluation 도메인)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M1-03 | INV-12 평가셋 구성(AC-04-1·3 도메인 부분) | 충족 | `tests/unit/evaluation/test_evalset.py` |
| TKT-BE-M1-03 | INV-05 test 문항 개발 사용 금지(AC-12-2 도메인 부분) | 충족 | `test_run_rules.py::test_ac_12_2_wrong_split_kind_rejected` |
| TKT-BE-M1-03 | INV-06 고정 후 변경 금지(AC-12-3 도메인 부분) | 충족 | `test_freeze.py::test_ac_12_3_…`, `test_run_rules.py::test_ac_12_3_…` |
| TKT-BE-M1-03 | GATE-02·04·07 | 충족 | §검증 결과 |

#### 만든 것 (`src/lawqa/evaluation/domain/`, 표준 라이브러리 + `shared.versioning`만)
- `errors.py`: `InvalidEvalDataError`(입력 오류, 종료 코드 1), `RuleViolationError(code, detail)`(종료 코드 3), 코드 상수 `TEST_SPLIT_IN_DEV`·`FROZEN_MISMATCH`·`LEAK_DETECTED`·`INVALID_RUN_KIND`
- `models.py`
  - `Split`(`dev`/`test`, `id_prefix`), `QuestionType`(`direct`/`paraphrase`/`no_evidence`)
  - `QuestionItem`(지문 + 보기 정확히 5개), `ExpectedAnswer`, `EvidenceRef`
  - `EvalQuestion` — 근거 없음: `answer=None`·`insufficient=True`·근거 비움·`absence_reason` 필수 / 답변 가능: `answer` 1~5·`key_facts≥1`·근거≥1 / `source`(`exam:2026:<문번>`·`authored`)·`answer_source`(`exam_key:DOC-05`·`human:<근거>`) 형식. `from_dict`·`to_dict`
  - `EvalSet` — ID `DEV-NN`/`TEST-NN`, 중복 금지, 구성 DEV(답변 가능 8·근거 없음 2)·TEST(직접 10·변형 7·근거 없음 3), `sha()`(정렬 JSON 해시), `get(qid)`, `answerable_count`
  - `SuccessCriteria` — 우선순위 `quality`·`latency`·`cost` 각 1번, 목표 6개 키와 범위(D-007), `sha()`
  - `FreezeStage`(`criteria`/`final`), `FreezeRecord` — `final`은 해시 4종·`index_version` 필수, `verify(current)`는 `git_commit`·`frozen_at`을 비교하지 않음, `criteria` 단계는 성공 기준 해시만 비교
- `run.py`
  - `RunKind`, `RunStatus`, `ALLOWED_KINDS`(dev: warmup·extra / test: main·retry·extra)
  - `Run` — `run_id` 형식 `<YYYYMMDD-HHMMSS>-<구성>-<종류>`, `make_id(started_at, config_name, kind)`, `check_allowed(kind, split, freeze, current, retry_of=None)`
  - `RunRecord` — `versions` 7키 필수(INV-11), `latency_ms` 5키, 오류면 `error_code` 필수, 재시도면 `retry_of` 필수, `counts_in_main_metrics`(main만)
- `metrics.py`: `FailureCategory`, `Grade`(값 0·1·없음, LLM 판정은 `judge_prompt_sha` 필수), `hit_at_5(record, question)`, `hit_at_5_total(records, questions) -> (합계, 분모)`, `MetricsRow`, `Metrics.compute`(임시: TKT-BE-M4-02)
- `ports.py`: `EvalSetRepository`, `SuccessCriteriaStore`, `FreezeStore`, `RunStore`(03-db-schema §7)
- 시험 3파일 43개, 가짜 평가셋 `tests/fixtures/eval/{dev,test}.json`(형식만 맞는 가짜 내용)

#### DB 에이전트에게 전달 (TKT-DB-M1-02)
- `JsonEvalSetRepository.load(split)`는 JSON을 읽어 `EvalSet.from_dict(data)`만 부르면 된다(검증은 도메인이 함). 성공 기준·고정 기록도 `SuccessCriteria.from_dict`·`FreezeRecord.from_dict`·`to_dict`.
- `RunStore.append`는 `RunRecord`를 한 줄 JSON으로 쓴다. `RunRecord`에는 아직 `to_dict`가 없다 — 03-db-schema §5 필드 순서대로 직렬화하되, 검색·답변 상세 필드(`queries`, `candidates`, `context_chunk_ids`, `context_chars`, `raw_output`, `answer`, `citations`)는 `details` 안에 그대로 들어 있다.

#### 임시 코드
- `Metrics.compute`가 `NotImplementedError` — TKT-BE-M4-02에서 구현하고 이 줄을 지운다.

#### 구현 중 자율 결정
##### TKT-BE-M1-03 dict ↔ 도메인 변환 위치
- 결정: `from_dict`·`to_dict`를 도메인 클래스에 둠 — 03-db-schema §7("dict ↔ 도메인")
- 선택지: **A. 도메인 클래스 (권장·채택)** / B. DB의 `files.py`
- 권장 이유: 검증 규칙과 필드 이름이 한곳에 있어 저장소는 파일 읽기·쓰기만 한다. 순수 함수라 도메인 규칙(표준 라이브러리만)을 지킨다.
- trade-off: A — 도메인이 파일 필드 이름(03-db-schema §5)을 안다. B — 필드 이름과 검증이 두 파일로 나뉜다.

##### TKT-BE-M1-03 `RunRecord`의 검색·답변 상세
- 결정: 03-db-schema §5의 검색·답변 상세 필드는 `details: Mapping[str, Any]`로 받음
- 선택지: **A. details 묶음 (권장·채택)** / B. 필드마다 타입 정의
- 권장 이유: `Candidate`·`Answer` 도메인은 retrieval·answering 티켓(M2·M3)에서 만들어진다. 지금 타입을 정하면 그 티켓과 겹친다.
- trade-off: A — 상세 필드의 형식 검사는 기록하는 쪽(TKT-BE-M3-05)이 한다. B — 아직 없는 타입을 미리 만들어야 한다.

##### TKT-BE-M1-03 성공 기준 목표 키 이름
- 결정: `hit_at_5`, `answer_correct`, `citation_valid`, `abstain_correct`(문항 수), `latency_median_s`(초), `call_success_rate`(0~1) — D-007, 03-db-schema §5(`targets: {...D-007}`)
- 선택지: **A. 지표 이름과 같은 키 (권장·채택)** / B. 비율로 통일
- 권장 이유: D-007이 "14/17"처럼 문항 수로 정했고, `Grade`·지표 이름과 같아 대조가 쉽다.
- trade-off: A — 키마다 단위가 다름(범위 검사로 보완). B — D-007 숫자를 바꿔 적어야 함.

#### 설계와 다르게 한 것 / 질문
- **`Run.check_allowed`에 `retry_of` 인자 추가**: 설계 시그니처에는 없지만 "RETRY면 retry_of 필수" 규칙을 검사하려면 필요하다(기본값 `None`, 기존 호출 형태 유지).
- **규칙 위반 코드 `INVALID_RUN_KIND` 추가**: 설계 코드 목록(`TEST_SPLIT_IN_DEV`·`FROZEN_MISMATCH`·`LEAK_DETECTED`)에 "dev 문항으로 본 평가·재시도"와 "재시도인데 원 실행 ID 없음"에 맞는 코드가 없다. test 문항 오용은 `TEST_SPLIT_IN_DEV`, 고정 없음·불일치는 `FROZEN_MISMATCH`를 그대로 쓴다. → ARCH에 04-interfaces-api §4 코드 목록 추가 요청.
- **고정 없음도 `FROZEN_MISMATCH`**: 본 평가인데 `FREEZE.json`이 없거나 `criteria` 단계뿐이면 `FROZEN_MISMATCH`로 거부한다(메시지에 `eval freeze --stage final` 안내).

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02 | 06-quality-gates GATE-02 명령 + evaluation 도메인 import 전수 확인 | 0줄(표준 라이브러리·`shared.versioning`·evaluation 도메인만) |
| GATE-04 | `uv run pytest tests/unit -q` | 81 passed(이번 티켓 43개 추가) |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-07 | 빈 except, 도메인의 시각·난수 | 0줄 |
| GATE-08 | `application`·`domain`의 저장 계층·LangChain import | 0줄 |

---

### TKT-BE-M1-04 (고정 서비스·`eval freeze`)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M1-04 | AC-02-1(성공 기준 파일의 우선순위·목표 6개) | 충족 | `SuccessCriteria` 검증(M1-03) + `test_ac_02_1_criteria_freeze_records_only_criteria_hash` |
| TKT-BE-M1-04 | AC-02-2(고정 커밋 순서 검사 기능) | 충족 | `FreezeService.check_frozen_before(first_main_run_started_at)`, 시험 2개 |
| TKT-BE-M1-04 | `final` 재고정 거부 | 충족 | `test_final_refreeze_rejected_and_not_overwritten`(final 뒤 criteria·final 모두 거부, 파일 그대로) |
| TKT-BE-M1-04 | 커밋 안 된 변경 있으면 거부 | 충족 | `test_final_freeze_rejected_with_uncommitted_changes` |
| TKT-BE-M1-04 | GATE-04 | 충족 | 단위 91·통합 29 = 120 passed |

#### 만든 것
| API | 명령 | 결과 | 종료 코드 |
|---|---|---|---|
| API-06 | `python -m lawqa eval freeze --stage criteria\|final` | `eval/FREEZE.json` 기록, 다음 할 일(커밋·태그) 안내 | 0 / 1(입력 오류: 파일 없음, 프롬프트·색인 없음, git 오류) / 3(규칙 위반) |
- `evaluation.application.FreezeService`
  - `freeze(kind: Literal["criteria","final"]) -> FreezeRecord`
    - criteria: 성공 기준 해시 + git HEAD + 시각. 같은 기준으로 다시 하면 **처음 기록을 그대로 돌려줌**(시각 유지), 바뀐 기준이면 `FROZEN_MISMATCH`.
    - final: 성공 기준·평가셋(dev·test 해시를 합친 해시)·구성별 `config_sha`·`prompt_sha`·색인 판본·HEAD. 커밋 안 된 변경(추적 파일만)이 있으면 거부. 기존 criteria와 성공 기준이 다르면 거부.
    - 이미 final이면 어떤 단계든 거부(덮어쓰지 않음).
  - `current() -> FreezeRecord` — 저장 없이 지금 값으로 final 기록(본 평가 전 `verify`용, TKT-BE-M3-05가 씀)
  - `check_frozen_before(first_main_run_started_at: datetime) -> None` — AC-02-2
  - `GitInfo` Protocol(`head()`, `has_uncommitted_changes()`)
- `evaluation.infrastructure.git_info.SubprocessGitInfo` — `git rev-parse HEAD`, `git status --porcelain --untracked-files=no`
- `evaluation.infrastructure.build_freeze_service(settings, *, config_shas, prompt_sha, index_version, repo_dir=".")` (CONV-03 조립 함수)
- CLI: `_config_shas()`(A·B·C·C+R 각 `config_sha`), `_prompt_sha()`(`answering/infrastructure/prompts/answer.txt` + `retrieval/infrastructure/prompts/rewrite.txt` 해시, 없으면 입력 오류), `_complete_index_version()`(임시), `_PENDING_TICKETS`에서 `eval freeze` 제거
- 시험 `tests/unit/evaluation/test_freeze_service.py` 10개(가짜 저장소·git·시각)

#### 실측 (저장소 밖 임시 작업 폴더, 가짜 평가셋)
| 단계 | 결과 | 종료 코드 |
|---|---|---|
| `--stage criteria` | `FREEZE.json`에 성공 기준 해시·HEAD·시각 기록, 커밋·태그 안내 | 0 |
| 같은 기준으로 다시 | 처음 `frozen_at` 그대로 | 0 |
| `--stage final` | "프롬프트 파일이 아직 없습니다 … (TKT-BE-M3-03·M3-04에서 생성)" | 1 |
| 목표값 바꾼 뒤 criteria | `FROZEN_MISMATCH: 고정 이후 바뀐 항목: success_criteria_sha` | 3 |
- 이 저장소에는 `eval/`을 만들지 않았다(실제 고정은 사람이 M1에서 한다).

#### 임시 코드
- `cli._complete_index_version()`이 항상 입력 오류 — TKT-BE-M2-02(색인 서비스)에서 완료된 색인 판본 조회로 바꾼다. 그 전까지 `--stage final`은 실행되지 않는다(M3에서 쓰므로 일정 영향 없음).
- `Metrics.compute`(M4-02), `_PENDING_TICKETS` 남은 항목은 그대로.

#### 구현 중 자율 결정
##### TKT-BE-M1-04 criteria 재고정
- 결정: 같은 성공 기준이면 처음 기록을 그대로 두고, 바뀐 기준이면 거부 — INV-06, AC-02-2
- 선택지: **A. 같으면 유지·다르면 거부 (권장·채택)** / B. 언제나 새로 기록 / C. 두 번째부터 모두 거부
- 권장 이유: 실수로 다시 실행해도 고정 시각이 늦춰지지 않고(AC-02-2), 기준을 몰래 바꾸는 것은 막는다.
- trade-off: A — 결과를 보기 전 기준을 정말 고쳐야 하면 `FREEZE.json`을 사람이 지우고 다시 해야 함(커밋 기록에 남음). B — 고정 시각이 뒤로 밀림. C — 실수 재실행이 오류가 됨.

##### TKT-BE-M1-04 커밋 안 된 변경의 범위
- 결정: 추적 중인 파일의 변경만 보고, 추적하지 않는 새 파일은 무시 — SEQ-06
- 선택지: **A. 추적 파일만 (권장·채택)** / B. 새 파일까지
- 권장 이유: 고정 대상(평가셋·설정·프롬프트)은 모두 추적 파일이다. 작업 폴더의 무관한 새 파일(예: `docs/presentation/`)이 고정을 막지 않게 한다.
- trade-off: A — 아직 `git add` 안 한 새 프롬프트 파일은 놓칠 수 있음(그 경우 `_prompt_sha`가 파일을 읽어 해시에는 반영됨, 커밋 여부만 확인 못 함). B — 무관한 파일 때문에 고정이 막힘.

##### TKT-BE-M1-04 평가셋 해시 합치기
- 결정: `evalset_sha = sha256("dev:<dev 해시>\ntest:<test 해시>")` — ADR-014 `evalset_sha`(dev/test 파일 해시)
- 선택지: **A. 두 해시를 이름과 함께 합침 (권장·채택)** / B. 두 해시를 따로 저장
- 권장 이유: `FreezeRecord` 필드가 하나라 그대로 쓰고, 어느 쪽이 바뀌어도 값이 바뀐다.
- trade-off: A — 어느 파일이 바뀌었는지는 따로 비교해야 앎. B — 도메인 필드 추가 필요.

#### 설계와 다르게 한 것 / 질문
- `evaluation/infrastructure/git_info.py`·`evaluation/infrastructure/__init__.py`(조립 함수)를 추가로 만들었다(티켓 산출 목록에는 없지만 AGENTS.md BE 쓰기 범위 안, git 읽기를 응용 계층 밖에 두기 위함).
- 없음(설계 충돌).

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b | 도메인 외부 import, 도메인·응용의 infrastructure import, corpus 역방향 | 각 0줄 |
| GATE-03 | 패키지 import 확인 | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 91 passed |
| GATE-04b | `uv run pytest tests/integration -q` | 29 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-07·08·09 | 빈 except, 저장 계층 누출, 정답 경로 | 각 0줄 |

---

### TKT-BE-M2-01 (corpus 도메인·청킹)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M2-01 | `PrecService` 변환(민사만, 법원명 필터 없음, 필드 매핑), 날짜, HTML 정제 | 충족 | `test_source_document.py`, `test_text_clean.py` |
| TKT-BE-M2-01 | 민법 텍스트 파서(ADR-015 규칙 전부) | 충족 | `test_statute_parser_*` 4개 |
| TKT-BE-M2-01 | 범위 밖·빈 본문·날짜 오류·중복 → 사유(AC-05-4 도메인 부분) | 충족 | `InvalidSourceDocumentError.reason`, `StatuteParseReport.issues` |
| TKT-BE-M2-01 | 판시사항·판결요지 `[n]` 묶음, `location` 형식 | 충족 | `test_chunking.py` |
| TKT-BE-M2-01 | **수용 확인: `민법.txt` 전체 → 조문 1,116·삭제 77·중복 0** | 충족 | `test_ac_full_civil_act_file_parses_1116_articles` |
| TKT-BE-M2-01 | GATE-02·04 | 충족 | §검증 결과 |

#### 만든 것
- `corpus/domain/errors.py`: `InvalidSourceDocumentError(reason, detail)`, `OutOfScopeError`, 사유 상수(`MISSING_FIELD`·`BAD_DATE`·`JSON_ERROR`·`EMPTY_CONTENT`·`OUT_OF_SCOPE`·`DUPLICATE_ARTICLE`, 필드가 붙으면 `MISSING_FIELD:사건번호` 형식)
- `corpus/domain/text_clean.py`: `clean_text(s)` — `<br>`·`<p>`→줄바꿈, 다른 태그 제거, `html.unescape`, 줄 끝 공백 제거, 빈 줄 여러 개→1개
- `corpus/domain/models.py`
  - `DocumentKind`, `SourceLocation`(`article_label`, `for_article(no, branch, paragraph_range)`, `for_precedent(decided_on, case_number, item_no, court="대법원")`)
  - `SourceDocument` — 생성 검증(INV-02), `location`, `from_prec_service(obj, source_file)`, `statute_articles_from_text(text, source_file) -> (docs, StatuteParseReport)`
  - `StatuteParseReport{articles, deleted, headings, dropped_lines, issues}`, `ImportIssue`, `Chunk`(chunk_id 형식 검사), `IndexVersion`(`compute_id`, `collection_name()`), `collection_name_for(index_version)`
- `corpus/domain/chunking.py`: `ChunkingPolicy(max_chars, overlap_chars).split(doc, index_version, tokenize) -> list[Chunk]`
- `corpus/domain/ports.py`: `PrecFile`, `CollectorReader`, `Tokenizer`, 저장소 4종(`ImportIssueRepository`는 CR-007대로 `corpus_version`), `VectorIndex`
- `corpus/infrastructure/collector_reader.py`: `FileCollectorReader` — `iter_prec_files`(판례일련번호 숫자 순, 깨진 JSON은 `PrecFile(data=None, error=…)`), `read_law_text`(BOM 허용), `list_law_files`
- `corpus/infrastructure/kiwi_tokenizer.py`: `KiwiTokenizer` — 내용 형태소(명사·동사·형용사 어간·어근·외국어·숫자·한자), Kiwi는 첫 호출 때 한 번 적재
- 시험 4파일 41개

#### 실데이터 확인 (저장소 밖 수집 폴더, 읽기만, 2026-11-24)
| 대상 | 결과 |
|---|---|
| 판례 파일 13,846건 | 변환 11,729건, `EMPTY_CONTENT` 2,117건(15%, 사람이 수집 후 삭제 예정 — HANDOFF §3), 다른 사유 0 |
| 판례 청크 | 16,442개(판례당 1~6개 이상), 최장 1,500자, 한도 초과 0 |
| 민법 1,116조 | 청크 1,116개(나눈 조문 없음), 최장 1,305자, 제목 줄 144(편·장·절·관 142 + 특수 2), 소속 없는 줄 0 |
- 항목 표시는 줄 머리의 `[n]`만 인정한다: 실제 판시사항에 "`[2] [1]항의 …`"처럼 본문 안 참조가 있어 모든 `[n]`에서 나누면 항목이 깨진다.
- 판시사항과 판결요지의 항목 수가 다른 판례가 드물게 있다(13,444건 중 15건): 번호 합집합으로 묶고 한쪽만 있는 항목도 남긴다.

#### 계층 확인 포인트
- `corpus/domain`은 표준 라이브러리(`json`·`re`·`html`·`dataclasses`·`datetime`·`enum`·`typing`·`collections.abc`)와 `shared.versioning`만 import(GATE-02 확인).
- 외부 라이브러리(`kiwipiepy`)는 `corpus/infrastructure/kiwi_tokenizer.py`에서만, 쓸 때 import.

#### 임시 코드
- 없음(이번 티켓). 이전 티켓의 임시 코드(`_complete_index_version`, `Metrics.compute`, `_PENDING_TICKETS`)는 그대로.

#### 구현 중 자율 결정
##### TKT-BE-M2-01 판례 위치의 법원명
- 결정: `location`에 `대법원` 고정 대신 판례의 `법원명`을 씀(`서울고법 1995. 12. 5. 선고 … 판결`) — ADR-015 개정(하급심 포함)
- 선택지: **A. 법원명 사용 (권장·채택)** / B. 언제나 "대법원"
- 권장 이유: 하급심 판결을 대법원 판결로 인용하면 틀린 출처가 된다(INV-01 취지).
- trade-off: A — 위치 문자열에 법원 이름 표기가 제각각(`서울고법`/`서울고등법원`). B — 하급심 출처가 틀림.

##### TKT-BE-M2-01 seq와 항목 번호
- 결정: `seq`는 문서 안 청크 순번(1부터), 항목 번호 `[n]`은 위치 문자열에만 — 03-db-schema §4(`seq=n`)
- 선택지: **A. 순번 (권장·채택)** / B. `seq = n`
- 권장 이유: 한 항목이 길어 여러 청크로 나뉘면 `seq=n`이 겹쳐 chunk_id가 중복된다. 나뉘지 않는 보통의 경우 순번과 n이 같다.
- trade-off: A — 항목 번호가 빠진 판례(예: [1],[3])는 seq와 n이 다름(위치 문자열로 확인). B — chunk_id 충돌.

##### TKT-BE-M2-01 청크 머리줄의 참조조문 길이
- 결정: 머리줄의 참조조문은 300자까지(넘으면 `…`), 전체는 `referenced_articles` 필드에 — 실데이터에서 참조조문 최대 1,914자로 청크 173개가 1,500자를 넘음
- 선택지: **A. 머리줄만 자름 (권장·채택)** / B. 자르지 않음(한도 초과 허용) / C. 머리줄에서 참조조문 제거
- 권장 이유: 한도(1,500자)를 지키면서 대부분(99%는 464자 이하)의 참조조문은 그대로 보인다.
- trade-off: A — 아주 긴 참조조문은 검색 본문에서 일부만 보임. B — 임베딩·프롬프트 길이 계산이 어긋남. C — 조문 번호로 찾는 검색이 약해짐.

##### TKT-BE-M2-01 색인 판본 id에 규칙 판본
- 결정: `compute_id` 해시에 `CHUNKING_RULES_VERSION`("1")을 넣음 — INV-11
- 선택지: **A. 규칙 판본 포함 (권장·채택)** / B. 설정 값만
- 권장 이유: 청킹 코드가 바뀌면 같은 설정이라도 다른 판본이 되어야 재현성이 지켜진다.
- trade-off: A — 규칙을 고칠 때 상수를 올리는 것을 잊지 말아야 함. B — 코드가 바뀌어도 같은 판본 id.

#### 설계와 다르게 한 것 / 질문
- **`CollectorReader.iter_prec_files` 반환형**: 설계는 `Iterator[tuple[str, dict]]`. 깨진 JSON을 `JSON_ERROR` 문제로 기록하려면 오류를 함께 넘겨야 해서 `Iterator[PrecFile(path, data | None, error)]`로 했다. → ARCH에 시그니처 갱신 요청.
- 위 "seq와 항목 번호"(03-db-schema §4의 `seq=n`과 다름, 나뉘지 않으면 같음) → ARCH에 문구 갱신 요청.
- `SourceLocation.for_precedent`에 `court` 인자(기본 "대법원") 추가 — 하급심 포함 결정(CR-005·006)의 반영.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02 | 06-quality-gates GATE-02 명령 + corpus 도메인 import 전수 확인 | 0줄 |
| GATE-02b | 모듈 역방향, 도메인·응용의 infrastructure import | 0줄 |
| GATE-04 | `uv run pytest tests/unit -q` | 132 passed(이번 티켓 41개) |
| GATE-04b | `uv run pytest tests/integration -q` | 29 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-07·09 | 빈 except·도메인 시각, 정답 경로 | 0줄 |

### TKT-BE-M2-02 (가져오기·색인 서비스·`corpus import/index`)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M2-02 | AC-05-1 색인 판본에 청크 크기·겹침·임베딩 모델·문서 수·청크 수 기록 | 충족 | `test_skipped_imports_leave_index_incomplete`, 시험 DB 실행 |
| TKT-BE-M2-02 | AC-05-2 청크 메타데이터(문서 ID·위치·판본, 판례는 참조조문) | 충족 | 청크는 M2-01 `Chunk`, 벡터 메타데이터는 DB-M2-02 `chunk_metadata` 그대로 |
| TKT-BE-M2-02 | AC-05-4 틀린 건은 건너뛰고 파일·줄·사유 기록, 색인 "불완전" | 충족 | `test_import_service.py`, `skipped=1 complete=false` 출력 |
| TKT-BE-M2-02 | GATE-10 출력 형식 | 충족 | `test_summary_line_matches_gate_10`, 시험 DB 실행 `chunks=16 embeddings=16` |
| TKT-BE-M2-02 | 재실행 시 같은 판본 "이미 있음" | 충족 | `test_rerun_*` 2개, 시험 DB 두 번째 실행 |
| TKT-BE-M2-02 | GATE-04 | 충족 | §검증 결과 |

#### 만든 것
- `corpus/application/import_service.py`: `ImportService.import_files(raw_dir) -> ImportReport{imported, issues, corpus_version, excluded, ignored_files}`(+`skipped`)
  - 판례: 깨진 JSON → `JSON_ERROR`, 변환 실패 → `InvalidSourceDocumentError.reason`. 성공 문서 500건 묶음 = 트랜잭션 1(SEQ-01)
  - 민법: `law/민법.txt` 없으면 `MissingStatuteFileError`(종료 1). 삭제 조문·제목 줄·소속 없는 줄은 `excluded` 건수, 다른 법령 파일은 `ignored_files`
  - 끝에 `corpus_version`(DB 전체 `content_sha` 정렬 해시)을 계산하고, 그 판본의 가져오기 문제를 지우고 다시 저장(CR-007, 재실행해도 쌓이지 않음)
- `corpus/application/index_service.py`: `IndexService.build_index(policy) -> IndexResult{version, embeddings, already_existed}`(`summary_line()` = GATE-10 한 줄), `IndexingError`
- `corpus/application/chunk_query_service.py`: `ChunkQueryService.list_chunks(index_version)`, `get_chunks(index_version, ids)`, `latest_complete_version()`
- `corpus/domain/models.py`: `corpus_version_of(content_shas)` / `corpus/domain/ports.py`: `TransactionScope`(연결의 `transaction()` 모양), 계약 보강(`VectorIndex.delete`, `IndexVersionRepository.latest_complete`, `ChunkRepository.count`, `ImportIssueRepository.list_for` — DB-M2-01·02가 이미 구현한 메서드)
- `corpus/infrastructure/__init__.py`: `build_import_service(conn)`, `build_index_service(conn, settings, *, database_url, embeddings=None, clock=None)`, `build_chunk_query_service(conn)`, `openai_embeddings(settings)`(`max_retries=3`), `chunking_policy(settings)`
- `entrypoints/cli.py`: `corpus import [--raw-dir]`(API-02), `corpus index [--config]`(API-03). `_PENDING_TICKETS`에서 두 항목 삭제. **임시 `_complete_index_version()`을 `ChunkQueryService.latest_complete_version()`으로 교체**(없으면 입력 오류)
- 시험: `tests/unit/corpus/conftest.py`(가짜 저장소·벡터·트랜잭션·시계), `test_import_service.py` 5개, `test_index_service.py` 9개

#### 계층 확인 포인트
- 응용 서비스는 `TransactionScope` 계약만 쓰고 psycopg·LangChain을 import하지 않는다(GATE-08 0줄). 운영에서는 psycopg `Connection`을 그대로 넘긴다.
- 트랜잭션: 가져오기 묶음마다 1, 문제 기록 1 / 색인은 판본 행+청크 교체 1, 벡터 적재(PGVector 자체 커밋), 완료 표시 1(SEQ-02).
- `langchain_openai`는 `corpus/infrastructure/__init__.py`의 `openai_embeddings`에서만, 쓸 때 import.

#### 보안 확인 포인트
- 접속 문자열·API 키는 `Settings.secrets.require(...)`로만 읽고 출력하지 않는다. DB 오류 메시지는 psycopg 메시지만 출력(접속 문자열 미포함).

#### 임시 코드
- `_complete_index_version` 임시 코드 제거(이번 티켓). 남은 임시: `Metrics.compute`(M4-02), `_PENDING_TICKETS` 나머지.

#### 구현 중 자율 결정
##### TKT-BE-M2-02 불완전으로 끝난 판본의 재실행
- 결정: 같은 판본이 `complete=true`이거나, **건너뜀이 기록되어 `complete=false`(불완전)로 끝났고 벡터 수 = 청크 수**이면 "이미 있음"으로 끝낸다 — 04-interfaces-api §8 SEQ-02("complete=true면 이미 있음")와 §9.2(건너뜀 > 0이면 false 유지)를 함께 따르면 불완전 판본은 실행할 때마다 다시 임베딩됨
- 선택지: **A. 끝난 불완전 판본도 "이미 있음" (권장·채택)** / B. 문서 그대로(`complete=true`만)
- 권장 이유: 실제 판례에는 빈 본문 2,117건이 있어 사람이 지우기 전까지 색인은 늘 불완전이다. B면 `corpus index`마다 청크 1만7천여 개를 다시 임베딩(비용·시간)한다.
- trade-off: A — 중단된 판본과 끝난 불완전 판본을 `skipped_count > 0`으로 구분하므로, 건너뜀 0인데 중단된 판본은 B와 같이 처음부터 다시 만든다(의도대로). B — 같은 입력에 매번 같은 결과를 다시 만드는 비용.

##### TKT-BE-M2-02 `build_index` 반환형
- 결정: `IndexVersion` 대신 `IndexResult{version, embeddings, already_existed}` — API-03 출력의 `embeddings=`(벡터 실제 수)와 "이미 있음" 표시가 필요
- 선택지: **A. 결과 객체 (권장·채택)** / B. `IndexVersion`만 반환하고 CLI가 벡터 수를 따로 조회
- 권장 이유: GATE-10의 "chunks = embeddings" 확인을 서비스가 한 곳에서 하고 그대로 출력한다.
- trade-off: A — 문서 시그니처와 다름(ARCH 갱신 필요). B — CLI가 벡터 저장소를 알아야 함.

#### 설계와 다르게 한 것 / 질문
- 위 두 자율 결정(`build_index` 반환형, 불완전 판본 재실행 규칙) → ARCH에 04-interfaces-api §2·§8 SEQ-02 갱신 요청.
- §2 표의 "파일 하나 = 트랜잭션 하나"는 SEQ-01("500건 묶음 = 트랜잭션 1")과 다르다. SEQ-01을 따랐다(판례 4만여 파일을 파일마다 커밋하지 않음). → ARCH에 §2 문구 갱신 요청.
- `build_index_service`는 `database_url`을 따로 받는다: PGVector가 자체 SQLAlchemy 연결을 쓰므로 psycopg 연결에서 비밀번호가 든 URL을 다시 꺼내지 않는다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b | 06-quality-gates 명령 | 0줄 |
| GATE-03 | 모듈 import | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 146 passed(이번 티켓 14개) |
| GATE-04b | `uv run pytest tests/integration -q` | 46 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-06·07·08·09 | 06-quality-gates 명령 | 각 0줄(GATE-08은 ports.py 설명문의 "psycopg" 낱말을 고쳐 0줄) |
| GATE-10 | 시험 DB(`lawqa_test`)에 `DATABASE_URL`을 바꿔 `corpus import --raw-dir tests/fixtures/raw` → `corpus index` 두 번 | 가져옴 14·건너뜀 1(`OUT_OF_SCOPE`)·무시 `상법.txt`, `index_version=idx-d414a9e1-f86ae9e9 chunks=16 embeddings=16 skipped=1 complete=false`, 두 번째는 "이미 있음"(임베딩 호출 없음) |
| API-02 오류 | `corpus import --raw-dir tests/fixtures/raw/broken` | `민법.txt` 없음, 종료 코드 1 |
- 개발 DB(`lawqa`)의 실제 가져오기·색인(판례 1만여 건, 임베딩 비용 발생)은 하지 않았다. 사람이 수집 완료·빈 판례 삭제 후 `corpus import` → `corpus index`로 실행한다.

### TKT-BE-M2-03 (retrieval 도메인)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M2-03 | R-3 입력 검증(AC-09-4 도메인 부분: 잘못된 부분 안내) | 충족 | `test_exam_item.py` — `InvalidExamItemError.field`가 `stem`·`options`·`options[n]` |
| TKT-BE-M2-03 | 라운드로빈 합침·중복 제거(ADR-011) | 충족 | `test_question_list.py` |
| TKT-BE-M2-03 | `RetrievalConfig.comparable_key`(INV-08) | 충족 | `test_retrieval_config.py` |
| TKT-BE-M2-03 | GATE-02·04, LangChain import 없음 | 충족 | §검증 결과 |

#### 만든 것
- `retrieval/domain/errors.py`: `InvalidExamItemError(field, reason)`, `RewriteFailedError`, `RetrievalFailedError`
- `retrieval/domain/models.py`
  - `ExamItem(stem, options)` — 지문 비어 있지 않음·≤4,000자, 보기 정확히 5개·각 비어 있지 않음·≤1,000자. 목록을 받으면 튜플로 바꿔 둔다
  - `RetrievalMode`(A/B/C), `RetrievalConfig` — 이름↔모드↔리라이트 일치(`A→A`, `B→B`, `C→C`, `C+R→C+리라이트`), 정수 ≥1, weights 0 이상·합 > 0. `comparable_key = (n_vec, n_bm25, n_fuse, k_opt, rrf_c, weights)`
  - `OptionQuery(option_no, original, rewritten=None, fallback=False)` + `effective`
  - `Candidate`(순위는 1 이상), `OptionResult`(`final_rank` 오름차순·청크 중복 없음, `top(k)`), `RetrievalResult`(보기 1~5 순서, `question_list(max_len=20)`, `context(k_opt)`)
- `retrieval/domain/decomposer.py`: `QueryDecomposer.decompose(item)` — 질의 = `지문(앞뒤 공백 제거) 앞 300자 + "\n" + 보기 원문`
- `retrieval/domain/ports.py`: `OptionRetriever.retrieve(query) -> list[Candidate]`, `QueryRewriterPort.rewrite(item, queries)`
- 시험 4파일 36개(`test_retrieval_config.py`는 티켓 산출 목록 밖이지만 `comparable_key` 완료 조건 확인용으로 추가)

#### 계층 확인 포인트
- `retrieval/domain`은 표준 라이브러리만 import(LangChain 없음, GATE-02 0줄).

#### 구현 중 자율 결정
##### TKT-BE-M2-03 `context(k_opt)`의 중복 청크
- 결정: 보기별 상위 `k_opt` 합집합에서 같은 청크는 처음 나온 보기 자리에 한 번만 — 04-interfaces-api §1.3 "합집합"
- 선택지: **A. 한 번만 (권장·채택)** / B. 보기마다 그대로(중복 허용)
- 권장 이유: "합집합" 정의와 같고, 같은 근거를 프롬프트에 두 번 넣지 않는다.
- trade-off: A — 모델이 "이 청크가 보기 3에도 해당"을 위치로 알 수 없음(보기별 근거 판단은 프롬프트 몫). B — 컨텍스트가 길어지고 인용 ID가 겹침.

##### TKT-BE-M2-03 `RetrievalConfig` 이름·모드 일치 검사
- 결정: 생성할 때 이름과 모드·리라이트가 맞지 않으면 `ValueError` — INV-08(바뀌는 것은 검색 구성과 리라이트 여부뿐)
- 선택지: **A. 생성 시 검사 (권장·채택)** / B. 검사 없음
- 권장 이유: 설정 파일 실수(`C.toml`에 `use_rewrite=true` 등)로 비교가 섞이는 것을 실행 전에 막는다.
- trade-off: A — 새 구성 이름을 추가하려면 대응표를 고쳐야 함. B — 잘못된 조합이 기록까지 감.

#### 설계와 다르게 한 것 / 질문
- 없음.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b | 06-quality-gates 명령 | 0줄 |
| GATE-03 | 모듈 import | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 182 passed(이번 티켓 36개) |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-07·09 | 06-quality-gates 명령 | 0줄(GATE-09가 변수 이름 `expected`에 걸려 `want`로 바꿈) |

### TKT-BE-M2-04 (검색 구성 A·B)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M2-04 | AC-06-1 구성 A: 벡터 후보 목록과 점수 기록 | 충족 | `test_config_a_records_vector_rank_and_score`, 시험 DB 실제 검색 |
| TKT-BE-M2-04 | AC-07-1 구성 B: BM25·벡터·결합 후보가 각각 기록 | 충족 | `Candidate.bm25_rank/score`·`vector_rank/score`·`fused_rank`, `test_config_b_fuses_with_rrf_and_dedupes_by_chunk_id` |
| TKT-BE-M2-04 | AC-07-2 같은 청크는 결합 후보에 한 번 | 충족 | 같은 시험, 시험 DB 실행에서 보기 목록 중복 없음 |
| TKT-BE-M2-04 | 점수 단순 합산 금지(가중 RRF) | 충족 | `EnsembleRetriever.weighted_reciprocal_rank`, `test_rrf_is_not_score_sum` |
| TKT-BE-M2-04 | GATE-02·04·08 | 충족 | §검증 결과 |
- AC-06-1·07-1의 "임베딩 모델·검색 개수·결합 방식·가중치·중복 제거 규칙 기록"은 실행 기록(`versions`·`config_sha`)에 남는 값이라 기록 쪽은 TKT-BE-M3-05(`eval run`) 몫이다. 이번 티켓은 그 값을 담은 `RetrievalConfig`와 후보별 순위·점수를 만든다.

#### 만든 것
- `retrieval/infrastructure/retrievers.py`
  - `Bm25Search` — `BM25Retriever`(langchain_community)를 청크 표의 `bm25_tokens`로 만든 `BM25Okapi`와 Kiwi 질의 토큰화(`preprocess_func`, S-02)로 조립. `search(query, k)`는 점수 > 0인 상위 k개를 순위·점수와 함께
  - `VectorSearch` — `PGVector`(컬렉션 `chunks_<index_version>`) `similarity_search_with_score`, 점수 = `1 - 코사인 거리`
  - `VectorOptionRetriever`(구성 A, 상위 `n_vec`), `HybridOptionRetriever`(구성 B: BM25 `n_bm25` + 벡터 `n_vec` → `EnsembleRetriever(weights, c=rrf_c, id_key="chunk_id")` 가중 RRF → 상위 `n_fuse`)
  - 외부 오류는 `RetrievalFailedError`로 바꿔 다시 던짐(삼키지 않음)
- `retrieval/application/retrieval_service.py`: `RetrievalService.retrieve(item, config, queries=None) -> RetrievalResult`
- `retrieval/infrastructure/__init__.py`: `retrieval_config(settings)`, `RetrieverFactory`(BM25 색인·PGVector는 처음 쓸 때 한 번, 같은 구성의 검색기 재사용, 구성 C는 M3-01 전까지 `RetrievalFailedError`), `build_retrieval_service(chunks, settings, *, index_version, sqlalchemy_url, embeddings, tokenize)`
- 시험 `tests/unit/retrieval/test_retrieval_service.py` 15개(가짜 검색기·가짜 벡터 검색, BM25는 실제 rank_bm25)

#### 계층 확인 포인트
- LangChain·rank_bm25는 `retrieval/infrastructure`에서만. 응용 서비스는 도메인 계약(`OptionRetriever`)만 안다(GATE-08 0줄).
- 05-structure-conventions §4 "다른 모듈의 infrastructure import 금지": 청크는 `corpus.application.ChunkQueryService`로 받고, Kiwi 토큰화(`corpus.infrastructure.KiwiTokenizer`)·임베딩·SQLAlchemy URL은 진입점이 넘긴다(`retrieval/`에서 `lawqa.corpus.infrastructure` 0줄).
- S-01 확인: `EnsembleRetriever`는 `langchain_classic.retrievers`에서 import된다(`langchain.retrievers`는 langchain 1.5.2에 없음).

#### 구현 중 자율 결정
##### TKT-BE-M2-04 결합은 같은 목록에 RRF를 한 번 적용
- 결정: BM25·벡터 목록을 한 번씩 구해(기록용 순위·점수) 그 목록에 `EnsembleRetriever.weighted_reciprocal_rank`를 적용 — ADR-009 "결합 전 각 검색기 결과는 기록용으로 따로 호출"
- 선택지: **A. 목록을 한 번 구하고 같은 목록으로 결합 (권장·채택)** / B. 기록용 호출과 `ensemble.invoke`를 따로
- 권장 이유: B는 보기마다 질의 임베딩을 두 번 불러 비용·시간이 두 배이고, 두 호출 결과가 달라지면 기록과 결합이 어긋난다.
- trade-off: A — `EnsembleRetriever.invoke` 경로 대신 같은 클래스의 결합 메서드를 직접 부름(라이브러리가 바뀌면 확인 필요). B — 호출 2배, 기록 불일치 가능.

##### TKT-BE-M2-04 BM25 점수 0은 후보에서 뺌
- 결정: 질의 낱말이 하나도 겹치지 않는(점수 0) 청크는 BM25 목록에 넣지 않는다
- 선택지: **A. 점수 > 0만 (권장·채택)** / B. `BM25Retriever` 기본대로 점수와 상관없이 상위 k개
- 권장 이유: B는 관련 없는 청크가 임의 순서로 BM25 목록에 들어가 RRF 결합에 섞인다.
- trade-off: A — BM25 목록이 k개보다 짧을 수 있음(기록에 그대로 보임). B — 무관한 청크가 결합 후보로 올라올 수 있음.

##### TKT-BE-M2-04 BM25 색인은 저장된 토큰으로
- 결정: 기동할 때 청크를 다시 형태소 분석하지 않고 청크 표의 `bm25_tokens`로 `BM25Okapi`를 만든다 — ADR-009 "BM25 색인은 기동 시 DB 청크로 메모리에"
- 선택지: **A. 저장된 토큰 (권장·채택)** / B. `BM25Retriever.from_documents(preprocess_func=kiwi)`로 다시 분석
- 권장 이유: 같은 결과를 내면서 청크 수만 개의 형태소 분석을 기동마다 반복하지 않는다(토큰은 색인 판본에 묶여 있음).
- trade-off: A — 질의 토큰화와 색인 토큰화가 같은 Kiwi 규칙이어야 함(둘 다 `KiwiTokenizer`). B — 기동 시간 증가.

##### TKT-BE-M2-04 벡터 점수 표기
- 결정: PGVector가 주는 코사인 거리를 `1 - 거리`(코사인 유사도, 높을수록 관련)로 기록 — `check smoke`의 벡터 점수와 같은 뜻
- 선택지: **A. 유사도 (권장·채택)** / B. 거리 그대로
- 권장 이유: BM25 점수처럼 "클수록 관련"으로 맞춰 기록을 읽기 쉽다.
- trade-off: A — 라이브러리 원값과 다름(변환식은 이 문서와 코드 설명에). B — 점수 방향이 BM25와 반대.

#### 설계와 다르게 한 것 / 질문
- `RetrievalService.retrieve`에 선택 인자 `queries`(리라이트 결과)를 더했다. 04-interfaces-api SEQ-03은 리라이트를 `retrieve` 앞에서 하지만 §2 시그니처(`retrieve(item, config)`)에 질의를 넘길 자리가 없다. 인자가 없으면 문서 시그니처와 같게 동작한다. → ARCH에 §2 시그니처 갱신 요청.
- `build_retrieval_service`는 색인 판본을 인자로 받는다. 검색에 쓸 판본(가장 최근 완료 판본, 또는 불완전이어도 마지막 판본)은 진입점 티켓(M3-03 `ask`·M3-05 `eval run`)에서 정한다 — 실제 판례 색인은 빈 판례 삭제 전까지 `complete=false`라 `latest_complete()`만으로는 판본이 없을 수 있다. → M3-03 전에 확인 필요.
- `langchain_community`를 import하면 "sunset" 경고(DeprecationWarning)가 나온다. 동작에는 영향 없고, `BM25Retriever`는 ADR-009·S-02가 정한 부품이라 그대로 썼다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b | 06-quality-gates 명령 + `retrieval/`의 `lawqa.corpus.infrastructure` | 각 0줄 |
| GATE-03 | 모듈 import | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 197 passed(이번 티켓 15개) |
| GATE-04b | `uv run pytest tests/integration -q` | 46 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-06·07·08·09 | 06-quality-gates 명령 | 각 0줄 |
| 실제 연동 | 시험 DB에 fixtures 가져오기·색인(16청크) 후 구성 A·B로 5개 보기 검색(실제 OpenAI 임베딩·PGVector) | A: 보기마다 벡터 순위·점수, B: BM25·벡터 순위와 결합 순위, 보기 목록 중복 없음, 문항 목록 16개 |

### TKT-BE-M3-01 (검색 구성 C)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M3-01 | AC-08-1 재정렬 전 순위·후 순위 기록(입력 후보 수 `n_fuse`, 출력 `k_opt`) | 충족 | `Candidate.fused_rank`(전)·`final_rank`(후)·`rerank_score`, `test_output_order_follows_rerank_scores_not_fused_order` |
| TKT-BE-M3-01 | AC-08-2 출력 순서 = reranker 점수 순서(결합 점수 순서 아님) | 충족 | 같은 시험 + 시험 DB 실제 실행(보기 5개 모두 점수 내림차순) |
| TKT-BE-M3-01 | `reranker_device` 설정 반영 | 충족 | `huggingface_cross_encoder(model, device)`, `resolve_device`(cuda 불가 시 cpu + 경고) |
| TKT-BE-M3-01 | GATE-04, LLM 재정렬 없음 | 충족 | §검증 결과 |
- reranker 이름·입력 후보 수·출력 k의 실행 기록 저장은 `versions`·`config_sha`를 쓰는 TKT-BE-M3-05 몫이다.

#### 만든 것
- `retrieval/infrastructure/reranker.py`
  - `RecordingCrossEncoder` — CrossEncoder를 감싸 재정렬이 계산한 점수를 남김(S-04 확인: `CrossEncoderReranker.compress_documents`는 점수를 문서에 붙이지 않음)
  - `RerankOptionRetriever`(구성 C) — 구성 B 결과(상위 `n_fuse`) → `CrossEncoderReranker(top_n=k_opt)`(langchain_classic) → 상위 `k_opt`. 동점은 B 순서(정렬이 안정적). 모델 오류는 `RetrievalFailedError`
  - `resolve_device(requested)`, `huggingface_cross_encoder(model_name, device)`
- `retrieval/infrastructure/__init__.py`: `RetrieverFactory`가 구성 C를 조립(재정렬 모델은 처음 쓸 때 한 번 적재), `build_retrieval_service(..., cross_encoder=None)`(없으면 설정 `reranker`·`reranker_device`)
- 시험 `tests/unit/retrieval/test_rerank_order.py` 7개(가짜 점수)

#### 구현 중 자율 결정
##### TKT-BE-M3-01 재정렬 점수는 한 번만 계산
- 결정: ADR-010의 "`score()`로 따로 구해 기록" 대신 모델을 감싸 `CrossEncoderReranker`가 계산한 점수를 그대로 기록
- 선택지: **A. 감싸서 기록 (권장·채택)** / B. 재정렬 후 `score()`를 한 번 더
- 권장 이유: GPU 계산이 절반이고, 기록 점수와 실제 정렬에 쓴 점수가 반드시 같다(AC-08-2를 구조로 보장).
- trade-off: A — `CrossEncoderReranker` 내부가 `model.score`를 한 번 부른다는 점에 기대(라이브러리 갱신 때 시험으로 확인). B — 계산 2배.

##### TKT-BE-M3-01 `ContextualCompressionRetriever`는 조립하지 않음
- 결정: 같은 B 결과에 `CrossEncoderReranker.compress_documents`를 직접 적용 — M2-04와 같은 이유(기록용 B 순위·점수를 이미 구했으므로 기본 검색기를 다시 부르면 질의 임베딩이 두 번)
- 선택지: **A. 압축기 직접 적용 (권장·채택)** / B. `ContextualCompressionRetriever(base_retriever=Ensemble)`
- 권장 이유: 재정렬 전 순위(B)와 재정렬 입력이 같은 목록임이 보장된다.
- trade-off: A — ADR-010 조립 문구와 형태가 다름(부품은 같음). B — 호출 2배, 기록 불일치 가능.

#### 설계와 다르게 한 것 / 질문
- 위 두 결정(ADR-010 조립·점수 기록 방식) → ARCH에 ADR-010 문구 갱신 요청.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b·07·08·09 | 06-quality-gates 명령 + `retrieval/`의 다른 모듈 infrastructure import | 각 0줄 |
| GATE-04 | `uv run pytest tests/unit -q` | 204 passed(이번 티켓 7개) |
| GATE-04b | `uv run pytest tests/integration -q` | 46 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| 실제 연동 | 시험 DB 16청크, 구성 C로 5개 보기 검색(OpenAI 임베딩·PGVector·`bge-reranker-v2-m3` GPU, 캐시된 모델) | 보기마다 4개(`k_opt`), 재정렬 점수 내림차순, 결합 순위 7위 청크가 1위로 오르는 등 B 순서와 다름, 모델 적재 후 문항 1개 검색 3.8초 |

### TKT-BE-M3-02 (answering 도메인)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M3-02 | INV-01 후보 밖 인용 제거 | 충족 | `test_citations_outside_candidates_are_dropped_and_counted`, `test_only_invented_citations_for_answer_becomes_insufficient` |
| TKT-BE-M3-02 | INV-13 정답 보기 인용 0 → 근거 부족(R-2: 다른 보기 판단은 참고로 유지) | 충족 | `test_answer_option_without_citation_is_insufficient`, `test_insufficient_cases` |
| TKT-BE-M3-02 | INV-03 오류 결과는 번호 없음, 결과 종류별 오류 코드 | 충족 | `test_error_results_have_no_number`, `test_error_code_must_match_outcome` |
| TKT-BE-M3-02 | GATE-02·04, 모델 호출 없음 | 충족 | §검증 결과 |

#### 만든 것
- `answering/domain/errors.py`: `ModelCallError`, `ModelTimeoutError`(`ModelCallError` 하위), `ModelOutputFormatError`
- `answering/domain/models.py`
  - `Outcome`(+`is_error`), `ErrorCode`(§4 표 8종), `Verdict`(값 `correct/incorrect/insufficient` = 출력 스키마 낱말), `Citation`, `OptionJudgment`
  - `ModelOption`, `ModelAnswer(answer, sufficient, options, raw_output)` + `from_dict(data, raw_output)`(타입이 틀리면 `ModelOutputFormatError`)
  - `Answer(outcome, answer_no, judgments, error_code, user_message, dropped_citations)` — 생성 시 결과 종류별 규칙 검사, `Answer.error(outcome, code, message)`, `Answer.from_model_output(output, candidate_ids, locations)`(ADR-013 ①~④)
- `answering/domain/ports.py`: `AnswerGenerator.generate(item, context) -> ModelAnswer`
- 시험 `tests/unit/answering/test_answer_rules.py` 20개

#### 계층 확인 포인트
- `answering/domain`은 표준 라이브러리와 `retrieval.domain`(포트의 `ExamItem`·`Candidate`)만 import(모듈 방향 answering → retrieval).

#### 구현 중 자율 결정
##### TKT-BE-M3-02 고른 보기의 판단이 "incorrect"여도 답변
- 결정: 근거 부족 판정은 고른 보기가 `insufficient`이거나 인용이 없을 때만. `correct`/`incorrect`는 모두 답변 가능 — ADR-013 ③ "정답 판단 보기가 insufficient이면"
- 선택지: **A. insufficient만 근거 부족 (권장·채택)** / B. 고른 보기가 `correct`여야 답변
- 권장 이유: 선택형 문항의 절반가량은 "옳지 않은 것은?"이라 틀린 보기를 고르는 것이 정답이다.
- trade-off: A — 판단과 문항 방향(옳은/옳지 않은)의 일치는 검사하지 않음(프롬프트 몫, 실패 분석 대상). B — "옳지 않은 것" 문항이 모두 근거 부족이 됨.

##### TKT-BE-M3-02 오류 결과에 보기 판단을 두지 않음
- 결정: `INPUT_ERROR`·`RETRIEVAL_ERROR`·`MODEL_ERROR`는 `judgments=()`만 허용
- 선택지: **A. 비움 (권장·채택)** / B. 허용
- 권장 이유: 오류는 모델 판단이 없거나 믿을 수 없는 경우라 화면·채점에 판단이 섞이지 않게 한다(INV-03).
- trade-off: A — 형식 오류 때 모델이 낸 일부 판단은 `raw_output`(기록)으로만 남음. B — 오류 결과가 답처럼 보일 수 있음.

##### TKT-BE-M3-02 사용자 문구
- 결정: 답변 `"정답: N번"`, 근거 부족 `"정보 부족: 근거를 찾지 못했습니다"`(§4 표 문구). 오류 문구는 서비스가 §4 문구로 넘김
- 선택지: **A. §4 핵심 낱말 그대로 (권장·채택)** / B. 화면(FE)에서 만듦
- 권장 이유: CLI·화면·기록이 같은 문구를 쓴다(ADR-004).
- trade-off: A — 문구를 바꾸려면 도메인을 고쳐야 함. B — 표시 경로마다 문구가 달라질 수 있음.

#### 설계와 다르게 한 것 / 질문
- `ModelAnswer`에 `raw_output`(비교 제외)과 `from_dict`를 더했다. `AnswerEnvelope.raw_output`(§2)을 생성기 한 번의 반환으로 넘기기 위해서다.
- 인용 중복(같은 보기에 같은 청크 두 번)은 한 번만 남기고 `dropped_citations`에 세지 않는다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b·07·09 | 06-quality-gates 명령 | 각 0줄 |
| GATE-04 | `uv run pytest tests/unit -q` | 224 passed(이번 티켓 20개) |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |

### TKT-BE-M3-03 (생성·AnswerService·`ask`)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M3-03 | AC-09-1 성공: 번호 1개·보기 5개 판단·정답 보기 인용 | 충족 | `test_answered_with_citations_inside_candidates_and_context_record`, 시험 DB 실제 `ask --config C` → ANSWERED 1번, 인용 `민법 제2조` |
| TKT-BE-M3-03 | AC-09-2 인용 ⊂ 그 실행의 후보 | 충족 | 같은 시험 + `test_citation_outside_context_becomes_insufficient` |
| TKT-BE-M3-03 | AC-09-3 색인 밖 법률 → 근거 부족 | 충족 | `test_insufficient_evidence_is_not_an_error`, 실제 `ask --config B`(상법 문항) → INSUFFICIENT_EVIDENCE |
| TKT-BE-M3-03 | AC-09-5 모델 실패 → 모델 오류(근거 부족 아님) | 충족 | `test_model_failure_is_model_error_not_insufficient`(호출·시간 초과·형식) — 실제로도 아래 temperature 400이 MODEL_CALL_FAILED로 기록됨 |
| TKT-BE-M3-03 | AC-09-6 검색 실패 → 검색 실패 | 충족 | `test_retrieval_failure_is_retrieval_error_not_insufficient`(검색·색인 없음·재정렬) |
| TKT-BE-M3-03 | AC-09-8 사용 청크 ID·위치·컨텍스트 수·길이 | 충족 | `AnswerEnvelope.context`·`context_chars`·`to_dict()["context"]` |
| TKT-BE-M3-03 | 모든 예외가 `Answer`로, GATE-04·07 | 충족 | `test_unexpected_exception_becomes_unexpected_model_error`, §검증 결과 |
- AC-09-4(입력 오류 시 검색·생성 호출 없음)도 서비스 수준으로 확인(`test_input_error_makes_no_search_or_model_call`). AC-09-7(문서 속 지시)은 프롬프트 규칙과 문서 이스케이프까지 확인했고(`test_prompt_file_loads_and_escapes_documents`), 실제 모델 응답 확인은 QA 수용 시험 몫.

#### 만든 것
- `answering/infrastructure/prompts/answer.txt` — `### SYSTEM`(역할·규칙 ①~⑤, §5.1)·`### USER`(`$question`, `$documents`). 파일 해시 = `prompt_sha`
- `answering/infrastructure/generator.py` — `AnswerPrompt`(문서는 `<doc id location>`, 본문 `<>&` 이스케이프), `ANSWER_SCHEMA`(strict JSON 스키마), `OpenAIAnswerGenerator`(`with_structured_output(method="json_schema", include_raw=True, strict=True)`, 오류 → `ModelTimeoutError`·`ModelCallError`·`ModelOutputFormatError(raw_output)`), `chat_model(...)`
- `answering/infrastructure/__init__.py`: `build_generator(settings)`
- `answering/application/answer_service.py` — `AnswerService.answer(item_input, config_name) -> AnswerEnvelope`(SEQ-03), `AnswerEnvelope{answer, config_name, retrieval, context, prompt_sha, raw_output, latency_ms, queries}` + `to_dict()`
- `entrypoints/composition.py` — `build_answer_runtime(conn, database_url, ...)`(corpus·retrieval·answering infrastructure 조립, 검색 판본 = `ChunkQueryService.search_version()`), `AnswerRuntime.index_warning()`
- `entrypoints/cli.py` — `ask --config --file`(API-05): 결과 JSON 출력, 오류 결과도 종료 0, 입력 파일 오류 1, DB 연결 실패 2, 불완전·없는 색인은 stderr 경고
- 보강: `retrieval/domain/errors.py` `IndexNotReadyError`·`RerankerFailedError`(`RetrievalFailedError` 하위, §4 코드 구분), 재정렬기는 `RerankerFailedError`, 검색기 공장은 판본이 없으면 `IndexNotReadyError` / `RetrievalService.decompose(item)` / `corpus` `ChunkQueryService.search_version()`·포트 `latest_finished`(CR-008) / `ModelOutputFormatError.raw_output` / `AnswerGenerator.prompt_sha`
- 시험 `tests/unit/answering/test_answer_service.py` 24개

#### 계층 확인 포인트
- `AnswerService`는 LangChain·OpenAI를 모른다(GATE-08). 예외 → 결과 변환은 여기 한 곳(`except Exception`은 `log.exception` 후 UNEXPECTED, ADR-004의 유일한 예외).
- 화면·기록 문구는 §4 문구만, 예외 원문은 로그 한 줄(`event=answer_failed code=… error=…`)에만.
- 모듈 사이 infrastructure 조립은 `entrypoints/composition.py`에만(05 §4).

#### 보안 확인 포인트
- API 키·DB URL은 설정에서만 읽고 출력·로그에 넣지 않음. 모델에 보내는 것은 문항과 검색된 청크뿐(INV-04: 평가 정답 없음, GATE-09 0줄).

#### 임시 코드
- 없음. 리라이트 단계는 SEQ-03대로 서비스에 있고(실패 → 모두 fallback), 리라이터 구현(`rewriter.py`)과 연결은 TKT-BE-M3-04에서. 그 전까지 `C+R`은 리라이트 없이 C와 같은 질의로 검색한다.

#### 구현 중 자율 결정
##### TKT-BE-M3-03 검색 판본 선택 (사용자 결정, CR-008)
- 결정: 완료 판본 우선, 없으면 끝난 가장 최근 판본(불완전)을 쓰고 경고 — 사용자 선택 2026-11-24
- 선택지: **A. 완료 우선, 없으면 마지막 (사용자 채택)** / B. 완료 판본만 / C. 설정에 판본 지정
- 권장 이유: 빈 판례 삭제 전에도 dev 조정을 할 수 있고, 본 평가 고정은 여전히 완료 판본만 허용한다.
- trade-off: A — 불완전 색인 결과가 섞일 수 있음(경고로 표시). B — 삭제·재색인 전까지 실행 불가. C — 재색인마다 설정 수정.
- DB 저장소 메서드는 `feat(db): CR-008` 커밋으로 따로 반영(`docs/03-db/briefing.md`).

##### TKT-BE-M3-03 `AnswerEnvelope` 필드 추가
- 결정: §2의 5개 필드에 `config_name`, `context`(모델에 넣은 후보), `queries`(보기별 질의·리라이트·fallback)를 더함 — AC-09-8, PAGE-01 "검색 정보", RunRecord(M3-05)가 같은 값을 쓴다
- 선택지: **A. 봉투에 담음 (권장·채택)** / B. 호출 쪽이 `RetrievalResult`에서 다시 계산
- 권장 이유: 모델이 실제로 받은 근거와 기록이 반드시 같다.
- trade-off: A — 문서 시그니처보다 큼(ARCH 갱신). B — 다시 계산한 값이 실제와 어긋날 수 있음.

##### TKT-BE-M3-03 문서 본문 이스케이프
- 결정: 근거 문서 본문의 `<`·`>`·`&`, 속성값의 따옴표를 HTML 이스케이프 — INV-09·AC-09-7
- 선택지: **A. 이스케이프 (권장·채택)** / B. 그대로
- 권장 이유: 문서 안의 `</doc>`가 태그를 닫고 지시처럼 보이는 것을 막는다.
- trade-off: A — 모델이 `&lt;` 같은 표기를 보게 됨(판례 본문에 꺾쇠는 드묾). B — 문서가 프롬프트 구조를 깰 수 있음.

#### 설계와 다르게 한 것 / 질문
- **`temperature=0`을 넘기지 않음**: §5.1은 `temperature=0`이지만 `gpt-6-luna`가 실제 호출에서 400("Only the default (1) value is supported")을 돌려줬다. 기본값(1)으로 호출한다. 같은 문항을 다시 물으면 답이 달라질 수 있어 재현성이 약해진다 → ARCH에 §5.1·S-06 갱신 요청(대안: 다른 생성 모델, `reasoning_effort` 조정 등은 사람 결정). §5.2 리라이트(M3-04)·§5.3 채점(M4-01)도 같은 문제가 있다.
- 위 `AnswerEnvelope` 필드, 조립 위치(`entrypoints/composition.py` — CONV-03은 `build_*`를 각 모듈 infrastructure에 두지만 모듈 사이 조립은 둘 곳이 진입점뿐) → ARCH 갱신 요청.
- `RetrievalService.retrieve`의 `queries` 인자(M2-04)를 SEQ-03의 리라이트 결과 전달에 그대로 썼다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b·06·07·08·09 | 06-quality-gates 명령 + answering의 다른 모듈 infrastructure import | 각 0줄(GATE-09가 로그 이벤트 이름 `answer_unexpected`의 "expected"에 걸려 `answer_crash`로 바꿈) |
| GATE-03 | 모듈 import | 종료 코드 0 |
| GATE-04 | `uv run pytest tests/unit -q` | 248 passed(이번 티켓 24개) |
| GATE-04b | `uv run pytest tests/integration -q` | 47 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| 실제 연동 | 시험 DB(16청크, 불완전 판본)에서 `ask --config C`(민법 제2조 문항), `ask --config B`(상법 문항) | C: ANSWERED 1번, 보기 5개 판단·인용, 컨텍스트 8청크 3,188자, 25.6초(재정렬 모델 적재 포함). B: INSUFFICIENT_EVIDENCE, 번호 없음, 6.1초. 두 번 모두 불완전 색인 경고 출력 |

### TKT-BE-M3-04 (쿼리 리라이트·C+R)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M3-04 | AC-10-1 원문항·보기별 변환 질의 기록, 검색 질의 = 변환 질의 | 충족 | `test_c_plus_r_searches_rewritten_queries_and_keeps_originals`, 실제 `ask --config C+R`(5개 보기 모두 법률 용어 질의, ANSWERED) |
| TKT-BE-M3-04 | AC-10-2 리라이트 실패 → 원문항으로 검색, fallback 표시 | 충족 | `test_whole_failure_falls_back_to_original_for_all_options`(시간 초과·연결·파싱), `test_missing_empty_or_too_long_option_falls_back_only_that_option` |
| TKT-BE-M3-04 | AC-10-3 리라이터 입력에 정답표·기대 답·허용 근거 없음 | 충족 | `test_rewriter_input_contains_only_stem_and_options`, 입력 타입이 `ExamItem`뿐 |
| TKT-BE-M3-04 | INV-10, GATE-04·09 | 충족 | §검증 결과 |

#### 만든 것
- `retrieval/infrastructure/prompts/rewrite.txt` — `### SYSTEM`(법률 용어 검색어, 판단·정답 추측 금지, 문항 속 지시 무시)·`### USER`(`$question`)
- `retrieval/infrastructure/rewriter.py` — `RewritePrompt`, `REWRITE_SCHEMA`(strict), `OpenAIQueryRewriter.rewrite(item, queries)`, `merge_rewrites`(보기별: 없음·빈 값·120자 초과 → 그 보기만 fallback), `chat_model`(`max_tokens=800`, 재시도 1회, 시간 제한 `rewrite_s`)
- `retrieval/application/retrieval_service.py` — 리라이트 단계를 검색 서비스로: `retrieve(item, config)`가 분해 → (C+R) 리라이트 → 검색. 전체 실패는 모두 fallback(`event=rewrite_fallback scope=all`), 일부 실패는 `scope=partial` 로그. `queries_for(item, config)` 공개
- `retrieval/infrastructure/__init__.py` `build_rewriter(settings)`, `build_retrieval_service(..., rewriter=)` / `entrypoints/composition.py`가 리라이터를 넘김
- `AnswerService`에서 M3-03의 리라이트 단계를 빼고, `AnswerEnvelope.queries`는 검색 결과의 보기별 질의에서 가져옴
- 시험 `tests/unit/retrieval/test_rewrite_fallback.py` 11개, 기존 시험 2개 수정

#### 구현 중 자율 결정
##### TKT-BE-M3-04 리라이트 단계 위치
- 결정: 리라이트를 `RetrievalService.retrieve` 안으로 옮김 — HANDOFF 산출 "retrieval_service.py(리라이트 단계)"와 §2 시그니처 `retrieve(item, config)`. SEQ-03 의사 코드는 AnswerService 안에 그렸음(문서끼리 다름, HANDOFF·§2를 따름)
- 선택지: **A. 검색 서비스 안 (권장·채택)** / B. AnswerService 안(M3-03 방식)
- 권장 이유: 검색 결과(`OptionResult.query`)가 실제로 쓴 질의·fallback을 함께 담아 기록이 한 곳에서 나오고, M2-04에서 더했던 `queries` 인자를 없애 §2 시그니처로 돌아간다.
- trade-off: A — SEQ-03 그림과 다름(ARCH 갱신). B — 질의를 두 서비스가 나눠 들고 다님.

##### TKT-BE-M3-04 리라이트 검색어만으로 검색
- 결정: 변환 질의는 지문 앞부분을 붙이지 않고 검색어 그대로 검색 — ADR-011 "보기별 질의를 법률 용어로 바꾸는 단계"
- 선택지: **A. 검색어만 (권장·채택)** / B. 지문 앞 300자 + 검색어
- 권장 이유: 리라이트 효과(C → C+R)를 질의 표현 차이로만 잰다. 검색어에 지문 맥락은 모델이 이미 반영한다.
- trade-off: A — 모델이 맥락을 빠뜨리면 검색이 좁아질 수 있음. B — 리라이트 효과가 희석됨.

#### 설계와 다르게 한 것 / 질문
- 위 "리라이트 단계 위치"(SEQ-03 그림) → ARCH 갱신 요청. M2-04 브리핑의 `retrieve(..., queries=None)` 인자는 없앴다.
- §5.2의 `temperature=0`도 생성기와 같은 이유(gpt-6-luna가 거부)로 넘기지 않는다.
- 리라이트 프롬프트 해시는 `eval freeze`의 `prompt_sha`(answer·rewrite 두 파일, M1-04)에 이미 들어간다. 이제 두 파일이 모두 있어 `_prompt_sha()`가 동작한다.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b·07·08·09 | 06-quality-gates 명령 | 각 0줄 |
| GATE-04 | `uv run pytest tests/unit -q` | 259 passed(이번 티켓 11개) |
| GATE-04b | `uv run pytest tests/integration -q` | 47 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| 실제 연동 | 시험 DB, `ask --config C+R`(민법 제2조 문항) | 보기 5개 모두 리라이트(예: "민법 제2조 권리남용 금지 원칙"), fallback 0, ANSWERED 1번, 28.2초(재정렬 모델 적재 포함). 색인이 없을 때는 RETRIEVAL_ERROR/INDEX_NOT_READY로 끝남도 확인 |

### TKT-BE-M3-05 (평가 실행 `eval run`)

#### 처리한 티켓
| TKT | 완료 조건 | 충족 여부 | 확인 방법 |
|---|---|---|---|
| TKT-BE-M3-05 | AC-12-1 본 평가 기록 버전 = 고정 값 | 충족(대역) | `test_main_runs_records_twenty_per_config_with_same_versions` — 본 평가는 `verify` 통과 뒤에만 시작, 기록 `versions`는 실행 머리와 같음 |
| TKT-BE-M3-05 | AC-12-2 test를 개발·튜닝(warmup)에 쓰면 거부 | 충족 | `test_test_split_warmup_is_refused_without_files_or_models`, CLI 종료 3 |
| TKT-BE-M3-05 | AC-12-3 고정 뒤 설정 변경 → 본 평가 거부, 추가 실험은 허용 | 충족 | `test_main_refused_when_settings_changed_after_freeze` |
| TKT-BE-M3-05 | AC-13-1 A·B·C·C+R × 20 = 80건 | 충족(대역) | 같은 본 평가 시험 |
| TKT-BE-M3-05 | AC-13-2 기록 필드(실행·질문 ID·구성·버전·후보와 점수·재정렬 전후·원본 답변·출처·시간·상태·종류) | 충족 | `test_dev_warmup_records_every_question_with_all_fields`, 실제 실행 기록 |
| TKT-BE-M3-05 | AC-13-3 재시도는 원 기록 유지 + 별도 RETRY, 본 지표 제외 | 충족 | `test_retry_records_failed_questions_separately_and_keeps_originals` |
| TKT-BE-M3-05 | AC-13-4 구성 간 생성 모델·프롬프트 버전 같음 | 충족(대역) | 본 평가 시험의 `versions` 비교 |
| TKT-BE-M3-05 | 중단 후 `--resume` | 충족 | `test_interrupted_run_resumes_without_duplicates`, 버전이 바뀌면 거부 |
| TKT-BE-M3-05 | GATE-04·11 | GATE-04 충족 / GATE-11 확인 못 함 | GATE-11은 `eval/`(평가셋·성공 기준·FREEZE.json, 사람 작업)이 없어 실행 불가. 같은 경로(`--dry-run`이 고정 비교까지 하고 파일·모델을 만들지 않음)는 `test_dry_run_plan_creates_nothing`으로 확인 |

#### 만든 것
- `evaluation/application/run_service.py`
  - `EvalRunService.plan(split, config, kind, *, retry_of, resume_run_id, only) -> RunPlan`(실행 전 검사만, `--dry-run`), `run(...) -> RunSummary`
  - 대상: `--only`(없는 ID는 입력 오류), 재시도면 원 본 평가 실행에서 `status != OK`인 문항(같은 split·구성 확인)
  - 이어 하기: 같은 split·구성·종류·retry_of인지, 버전이 같은지 확인 뒤 기록 없는 문항만
  - `build_record(run, question_id, started_at, envelope)` — 03-db-schema §5 필드로 변환. `status`: 검색·모델 오류 ERROR, `MODEL_TIMEOUT`은 TIMEOUT, 그 밖 OK. 재시도 기록 `attempt=2`
  - 답변기·현재 고정 값은 필요할 때만 만든다(규칙 위반이면 모델·DB 검색 자원을 적재하지 않음)
- `evaluation/infrastructure/__init__.py`: `build_run_service(settings, *, current_freeze, versions_for, answerer)`
- `entrypoints/cli.py` `eval run`(API-07): `--split --config --kind [--retry-of] [--resume] [--only] [--dry-run]`. 종료 코드: 규칙 위반 3, 입력 오류 1(파일 없음·이미 있는 실행 등), DB 연결 실패 2
  - 기록 `versions`: `corpus`·`index`(검색 판본), `config_sha`(구성별), `prompt_sha`(answer+rewrite, `eval freeze`와 같은 계산), `gen_model`, `embedding_model`(`모델/차원`), `reranker_model`
- 보강: `AnswerEnvelope.retrieval_ms`·`generation_ms`(단계 시간), `Run.check_allowed(current=None 허용)`
- 시험 `tests/unit/evaluation/test_run_service.py` 12개(임시 폴더의 실제 파일 저장소 + 대역 답변기)

#### 구현 중 자율 결정
##### TKT-BE-M3-05 단계별 시간
- 결정: `latency_ms`의 `retrieval`(리라이트·검색·재정렬 포함)과 `generation`만 잰다. `rewrite`·`rerank`는 `null`
- 선택지: **A. 두 단계만 (권장·채택)** / B. 네 단계 모두(검색 서비스 안에 시간 측정 추가)
- 권장 이유: 지표(REQ-075)는 전체 시간 중앙값만 쓴다. 단계 시간은 분석용이라 서비스 경계에서 재는 것으로 충분하다.
- trade-off: A — 리라이트·재정렬 시간을 따로 볼 수 없음(필요하면 나중에 검색 서비스에 추가). B — 측정 코드가 검색 내부로 퍼짐.

##### TKT-BE-M3-05 재시도 대상 기본값
- 결정: `--kind retry --retry-of RUN`은 원 실행의 오류·시간 초과 문항만 다시 한다(`--only`를 주면 그 문항)
- 선택지: **A. 실패 건만 (권장·채택)** / B. 전 문항
- 권장 이유: R-1·AC-13-3의 재시도는 "호출 오류가 난 건"이다.
- trade-off: A — 정상 건 재측정은 `--only`로 지정해야 함. B — 불필요한 호출·비용.

##### TKT-BE-M3-05 규칙 검사 순서
- 결정: 분할·종류·고정 기록 검사를 먼저 하고, 현재 값(평가셋·성공 기준·색인 판본)은 그 뒤에만 계산
- 선택지: **A. 규칙 먼저 (권장·채택)** / B. 현재 값 먼저
- 권장 이유: dev로 본 평가를 하려는 실수 같은 규칙 위반을 입력 파일 상태와 상관없이 종료 3으로 알린다.
- trade-off: A — 없음에 가까움. B — 평가셋이 없으면 규칙 위반이 입력 오류로 가려짐(실제 CLI에서 확인 후 고침).

#### 설계와 다르게 한 것 / 질문
- 기록 `versions.index`는 CR-008의 검색 판본(완료 우선, 없으면 끝난 최근)이다. 본 평가는 `eval freeze --stage final`이 완료 판본만 허용하고 `verify`가 같아야 하므로 본 평가 기록은 항상 완료 판본이다.
- `RunRecord.details`에 §5 목록 외에 `context`(청크 ID·위치·글자 수)를 더했다(AC-09-8의 위치 정보).
- `eval/`이 아직 없어 실제 명령으로는 규칙 위반·입력 오류 경로만 확인했다. 실제 모델 실행은 아래처럼 시험용 평가셋으로 확인.

#### 검증 결과
| 게이트 | 명령 | 결과 |
|---|---|---|
| GATE-02·02b·07·08·09 | 06-quality-gates 명령 | 각 0줄 |
| GATE-04 | `uv run pytest tests/unit -q` | 271 passed(이번 티켓 12개) |
| GATE-04b | `uv run pytest tests/integration -q` | 47 passed |
| GATE-05 | `uv run ruff check .` / `uv run ruff format --check .` | 통과 |
| GATE-11 | `eval run --split test --config C --kind main --only TEST-01 --dry-run` | 확인 못 함: `eval/success_criteria.json` 없음(종료 1). 사람이 평가셋·성공 기준·final 고정을 만든 뒤 실행 |
| CLI 종료 코드 | `eval run --split test --config C --kind warmup` / `--split dev --config C --kind main` | 둘 다 규칙 위반 종료 3 |
| 실제 연동 | 시험 DB(16청크)·시험용 평가셋(`tests/fixtures/eval`)으로 C+R 워밍업 2문항(실제 리라이트·임베딩·재정렬·생성), 결과는 임시 폴더 | 2건 즉시 기록, `status=OK`, 보기별 후보·리라이트(fallback 0)·컨텍스트·단계 시간(첫 문항 26.0초: 재정렬 모델 적재 포함, 둘째 9.4초) |

### CR-009·010 반영 (TKT-BE-M2-01·02 범위 변경, 2026-11-24)

새 티켓이 아니라, 승인된 CR-009·CR-010에 따라 이미 끝난 TKT-BE-M2-01·02의 입력 범위를 바꾼 작업이다
(`docs/PIPELINE.md` §2-9: 승인된 CR은 대상 단계가 반영하기 전에도 우선한다).

**무엇이 달라졌나**: 가져오기가 읽는 법령이 `law/민법.txt` 하나에서 `statutes/*.txt` 전부로 바뀌었다.

| 완료 조건 (CR-010) | 충족 여부 | 확인 방법 |
|---|---|---|
| `statutes/` 안의 `*.txt`를 전부 읽는다 | 충족 | `test_iter_statute_texts_reads_every_statute_in_name_order`, `test_every_statute_file_is_imported_under_its_own_law_name` |
| 법령 이름 = 파일 이름(확장자 제외), `doc_id = "law:<법령명>:<조>-<가지>"` | 충족 | 같은 시험 + 실제 13개 법령 파싱(아래) |
| `.txt`가 아닌 파일은 읽지 않고 보고에 적는다 | 충족 | `test_list_ignored_statute_files_reports_non_txt_only` |
| ADR-015 민법 확인 수치(1,116·77·0) 유지 | 충족 | `test_ac_full_civil_act_file_parses_1116_articles`(입력을 `statutes/민법.txt`로 바꿔 통과) |

#### 바꾼 것
- `corpus.domain.models`
  - 모듈 상수 `LAW_NAME = "민법"` **삭제**. 법령 이름은 이제 인자로 흐른다.
  - `SourceLocation.article_label(law_name, no, branch)`, `SourceLocation.for_article(law_name, no, branch, paragraph_range)` — 첫 인자로 법령 이름 추가.
  - `SourceDocument.statute_articles_from_text(text, source_file, law_name)` — 세 번째 인자 추가.
  - `SourceDocument.__post_init__`: 조문(`STATUTE_ARTICLE`)은 `law_name`이 비면 `InvalidSourceDocumentError(MISSING_FIELD)`. 법령이 여럿이라 이름 없이는 원문 위치를 만들 수 없다.
  - `SourceDocument.location`은 `self.law_name`을 쓴다.
- `corpus.domain.chunking`: `_article_pieces`·`_article_batch`가 문서의 `law_name`을 받아 위치 문자열에 넣는다.
- `corpus.domain.ports`: `StatuteFile(law_name, path, text)` 추가. `CollectorReader`의 `read_law_text`·`list_law_files` → `iter_statute_texts`·`list_ignored_statute_files`.
- `corpus.infrastructure.collector_reader`: `LAW_DIR="law"` → `STATUTE_DIR="statutes"`. `iter_statute_texts`가 `*.txt`를 이름 순으로 전부 읽는다(UTF-8, BOM 허용).
- `corpus.application.import_service`: 단일 파일 읽기 → 법령별 반복. `deleted`·`headings`·`orphan_lines`는 법령 전체 합계. `statutes/`에 `*.txt`가 하나도 없으면 `MissingStatuteFileError`.
- `config/base.toml` 주석, `shared/smoke.py` 주석의 경로 표기.
- `.gitignore`: `*.json`·`*.txt`가 `eval/*.json`, `results/**/*.json(l)`, `law_collector/data/statutes/*.txt`까지 무시하고 있었다. 세 경로에 negation을 넣었다(HANDOFF는 이 셋을 커밋 전제로 쓴다).

#### 실제 13개 법령 파싱 결과 (가져오기 전 확인, DB 적재 없음)
| 법령 | 조문 | 삭제 | 이슈 | 버린 줄 |
|---|---|---|---|---|
| 민법 | 1,116 | 77 | 0 | 0 |
| 상법 | 1,141 | 41 | 0 | 0 |
| 채무자 회생 및 파산에 관한 법률 | 697 | 2 | 0 | 0 |
| 민사소송법 | 523 | 0 | 0 | 0 |
| 민사집행법 | 311 | 1 | 0 | 0 |
| 부동산등기법 | 120 | 1 | 0 | 0 |
| 가사소송법 | 88 | 2 | 0 | 0 |
| 집합건물의 소유 및 관리에 관한 법률 | 84 | 4 | 0 | 0 |
| 어음법 | 78 | 0 | 0 | 0 |
| 주택임대차보호법 | 41 | 1 | 0 | 0 |
| 상가건물 임대차보호법 | 32 | 0 | 0 | 0 |
| 가등기담보 등에 관한 법률 | 18 | 0 | 0 | 0 |
| 부동산 실권리자명의 등기에 관한 법률 | 16 | 1 | 0 | 0 |
| **합계** | **4,265** | 130 | **0** | **0** |

ADR-015의 파서 규칙이 13개 법령 전부에서 이슈·버린 줄 0으로 적용된다. 민법 수치는 이전과 같다.

#### 구현 중 자율 결정
#### CR-010 `law_name`을 인자로 흘릴지, 파일 경로에서 뽑을지
- 결정: `StatuteFile(law_name, path, text)`를 읽기 어댑터가 만들어 도메인 파서에 인자로 넘긴다 — CR-010, ADR-001(도메인은 파일 체계를 모른다)
- 선택지: **A. 어댑터가 파일 이름에서 법령 이름을 뽑아 값 객체로 넘긴다 (권장·채택)** / B. 파서가 `source_file` 문자열을 파싱해 법령 이름을 얻는다
- 권장 이유: 도메인 파서가 `statutes/<이름>.txt`라는 경로 규칙을 알 필요가 없다. 어댑터만 파일 체계를 안다.
- trade-off: A — 포트 시그니처가 하나 늘어난다. B — 도메인이 경로 형식에 묶여 입력 폴더 구조가 바뀌면 도메인을 고쳐야 한다.

#### CR-009 조문의 `law_name`을 필수로 만들지
- 결정: `STATUTE_ARTICLE` 문서는 `law_name`이 비면 생성 거부 — CR-009, INV-02
- 선택지: **A. `__post_init__`에서 거부 (권장·채택)** / B. `location`에서 빈 이름을 허용하고 `" 제1조"`처럼 만든다
- 권장 이유: 법령이 하나일 때는 이름이 없어도 위치가 맞았지만, 이제는 조용히 틀린 인용이 만들어진다. 인용은 C-06의 핵심이라 빨리 실패하는 편이 낫다.
- trade-off: A — `SourceDocument`를 직접 만드는 코드가 `law_name`을 반드시 넘겨야 한다. B — 잘못된 인용이 평가 기록까지 흘러간다.

#### 설계와 다르게 한 것 / 질문 / DB 에이전트에게 요청
- **단계 경계를 넘어 고친 파일 3개(사후 승인 요청)**: `tests/fixtures/raw/law/` → `statutes/` 이름 바꾸기, `tests/integration/db/test_corpus_repositories.py`, `test_vector_index.py`, `test_schema.py`. 모두 `AGENTS.md` 단계 표에서 **DB 담당**이다. 포트 시그니처가 바뀌어 이 파일들이 그대로면 통합 시험이 깨진 채로 남기 때문에 함께 고쳤다. 내용 변경은 (a) 폴더 이름, (b) `read_law_text` 호출 → `iter_statute_texts` 반복, (c) 고정 건수 9 → 10(상법 픽스처가 이제 읽히므로)뿐이다. DB 단계가 다음 티켓에서 확인해 주기 바란다.
- **`ImportReport`에 법령별 조문 수를 넣지 않았다.** GATE-10 출력 형식이 04-interfaces-api에 정해져 있어 필드를 늘리면 출력 계약이 바뀐다. 필요하면 ARCH에 CR로 올린다.
- **미정(평가셋 작성을 막는다)**: CR-011의 `US-04` ④ "근거 없음" 문항(dev 2·test 3) 출처. 13개 법령이 민사법을 거의 덮어 "색인 밖 법률 문항"이라는 기존 정의가 성립하지 않는다. 사용자 결정 전에는 평가셋을 쓰지 않는다.
- **사람 영역 작업(사용자 지시 2026-11-24, PIPELINE §2-5 예외)**: 빈 본문 판례 6,706건을 `law_collector/data/prec_empty/`로 옮기고 `data/MANIFEST.md`를 썼다. 둘 다 `AGENTS.md`에서 사람 담당이다.

#### 검증 결과
| GATE | 명령 | 결과 |
|---|---|---|
| GATE-02·08·09 | 06-quality-gates 명령 | 각 0줄 |
| GATE-03 | `python -c "import lawqa.…"` | 종료 0 |
| GATE-04 | `uv run pytest tests/unit -q` | **288 passed** (이번 변경으로 추가 3개) |
| GATE-04b | `uv run pytest tests/integration -q` | **47 passed** |
| GATE-05 | `uv run ruff check .` / `ruff format --check .` | 통과 |
| 실제 입력 확인 | 13개 법령 파싱(위 표) | 조문 4,265, 이슈 0, 버린 줄 0. 민법 1,116·삭제 77 유지 |
| 실제 적재 | `python -m lawqa corpus import` (사용자 승인 2026-11-24) | 종료 0. **문서 40,096건(판례 35,831 + 조문 4,265), 건너뜀 0건, import_issues 0건.** 제외(오류 아님) deleted_articles=130, heading_lines=454, orphan_lines=0 |
| 멱등 | 같은 명령 2회 실행 | `corpus_version`·행 수 동일(40,096), 중복 없음 — AC-05-3 |
| GATE-10 | `python -m lawqa corpus index` (사용자 승인 2026-11-24) | **통과**. `index_version=idx-e7e52477-f86ae9e9 chunks=54969 embeddings=54969 skipped=0 complete=true` — `chunks`와 `embeddings`가 같고 `complete=true` |

`corpus import`의 **건너뜀 0건**은 ADR-015가 의도한 확인 장치가 통과했다는 뜻이다 — 빈 본문 판례 정리가 끝났으므로
색인이 `complete=true`가 될 수 있고 `eval freeze --stage final`이 막히지 않는다.
적재된 `corpus_version`: `e7e52477…54d10b5`

**색인 결과 (2026-11-24 14:23~14:29, 약 6분)**

| 종류 | 청크 | 문서 | 문서당 | 최대 길이 |
|---|---:|---:|---:|---:|
| PRECEDENT | 50,690 | 35,831 | 1.41 | 1,500자 |
| STATUTE_ARTICLE | 4,279 | 4,265 | 1.00 | 1,494자 |
| **합계** | **54,969** | **40,096** | | |

판례는 판시사항·판결요지의 `[n]` 항목 묶음과 1,500자 분할로 문서당 평균 1.41청크가 나왔고,
조문은 거의 "1조 = 1청크"(4,265조 → 4,279청크, 긴 조문 14개만 항 경계로 나뉨)다.
임베딩 API 550회(배치 100개), `langchain_pg_embedding` 54,969행으로 청크 수와 일치한다.

---
stage: BE
tickets: [TKT-BE-M1-01, TKT-BE-M1-02, TKT-BE-M1-03, TKT-BE-M1-04, TKT-BE-M2-01]
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

---
stage: BE
tickets: [TKT-BE-M1-01]
status: done
inputs_read: [AR-MAP, AR-HAND, AR-API, AR-CONV, AR-GATE]
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

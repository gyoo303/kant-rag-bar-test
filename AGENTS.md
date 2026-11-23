## 에이전트 파이프라인 규칙 (모든 작업에 적용)

이 저장소는 `PM → ARCH → DB → BE → FE → QA` (+ 횡단 UX) 에이전트 파이프라인으로 작업한다. 스킬을 쓰지 않는 작업에도 적용된다.

1. 문서 경로의 기준은 `docs/PIPELINE.md`(산출물 레지스트리) 하나다. 스킬 문서와 다르면 레지스트리를 따른다.
2. 파이프라인 단계 작업(기획·설계·DB·백엔드·프론트·QA·UX)은 해당 스킬(`pm-agent`, `architect-agent`, `db-agent`, `backend-agent`, `frontend-impl`, `qa-agent`, UX 스킬)을 로드해서 한다. 어떤 단계를 쓸지(예: UX 단계 사용 여부)는 프로젝트 프로파일(`docs/00-inputs/project-profile.md`) 제약 대장을 따른다.
3. 작업 전 `node scripts/check-handoff.mjs <STAGE>`를 실행한다(DB·BE·FE·QA는 `--ticket <TKT>`를 붙여 HANDOFF 선행 티켓의 브리핑까지 확인). 마지막 줄이 `STATUS: READY`가 아니면 작업하지 않고 그 STATUS 줄을 보고한 뒤 멈춘다. 사용자가 예외를 승인하면 `docs/PIPELINE.md` §2-5대로 기록한다.
4. 산출물은 레지스트리에서 `만드는 단계`가 내 단계인 경로에만 쓰고, 끝나면 `node scripts/check-handoff.mjs <STAGE> --post`로 확인한다(DB·BE·FE·QA는 `--ticket <TKT>`를 붙인다).
5. 순차 실행은 `scripts/run-stage.sh <STAGE> [TKT]`로 한다 (`docs/PIPELINE.md` §5).
6. 구현 단계(DB·BE·FE·QA)는 HANDOFF에 "요청 시" 표시가 없는 티켓을 먼저 구현한다. "요청 시" 티켓(프로파일 범위 등급의 하위 등급)은 사용자가 티켓을 지정해 따로 요청할 때만 착수하고, 다른 티켓에 그 범위를 미리 넣지 않는다.
7. 문서끼리 충돌하면 **프로파일의 `고정` 제약 → PM 산출물(`docs/01-pm/`) → ARCH 산출물(`docs/02-arch/`, 이 파일) → 스킬 문서** 순서로 따르고, 충돌 내용을 브리핑에 적는다. 단, PM 문서가 "후보"로 표시한 코드 식별자(클래스·메서드 이름 등)는 ARCH가 확정한 이름을 쓴다(충돌이 아니라 확정). 어느 문서에도 정의되지 않은 것은 스킬의 예시·기본값이나 추측으로 채우지 않고 **반드시 사용자에게 확인**한다(확인 요청은 선택지마다 무엇이 달라지는지·좋은 점·감수할 점·나중에 바꾸기를 쉬운 말로 함께 쓴다, `docs/PIPELINE.md` §2-7)(헤드리스: `STATUS: AWAITING_USER_DECISION <미정 항목>` 출력 후 종료).
8. 다른 단계가 만든 문서나 프로파일을 바꿔야 하면 직접 고치지 않고 `docs/change-requests.md`에 변경 요청(CR)을 남겨 사용자 승인을 받는다. 승인된 CR은 대상 단계가 반영하기 전에도 대상 항목보다 우선한다(`docs/PIPELINE.md` §2-9). 새 요구는 같은 문서에 다음 사이클로 덧붙인다(§6).
9. 프로젝트 고유 규칙(코드 수준 기준, 특정 결정·마일스톤에 묶인 규칙 등)은 이 섹션에 두지 않는다. 프로파일 제약(C-ID)이나 ARCH 산출물(ADR, `05-structure-conventions.md`)에 두고, ARCH가 이 파일의 디렉토리 지도 섹션에서 위치를 안내한다.

<!-- 디렉토리 지도 섹션(제목 "디렉토리 지도", h2)은 ARCH가 A6에서 프로젝트 설계에 맞춰 만든다. 섹션이 없으면 DB·BE·FE·QA 점검(AR-MAP)이 막힌다. -->

## 디렉토리 지도

> 프로젝트: 민법 선택형 문항 RAG 에이전트(C1). 설계 기준: `docs/02-arch/` (ADR-001 모듈 구조, `05-structure-conventions.md` 트리·금지 패턴·스택 주의). UX 단계: 사용 안 함(C-16).

| 경로 | 책임 |
|---|---|
| `src/lawqa/corpus/` | 사용자 수집 JSONL 가져오기, 청킹, PostgreSQL 저장, PGVector 색인 |
| `src/lawqa/retrieval/` | 보기별 분해, 쿼리 리라이트, 구성 A/B/C 검색(BM25·PGVector·Ensemble·Reranker) |
| `src/lawqa/answering/` | 근거 기반 답변, `Answer` 결과(오류 변환 유일 위치) |
| `src/lawqa/evaluation/` | 평가셋·고정·일괄 실행·채점·지표. **정답(`eval/`)을 읽는 유일한 모듈** |
| `src/lawqa/shared/` | 설정·DB 연결·버전 해시·시각 |
| `src/lawqa/entrypoints/` | `cli.py`(`python -m lawqa ...`), `streamlit_app.py` |
| `config/` | 실험 설정(커밋), 구성 A/B/C/C+R |
| `eval/`, `results/` | 평가셋·고정 기록, 실행 기록(커밋, append 전용) |
| `data/` | 원문 JSONL(커밋 안 함, `MANIFEST.md`만 커밋) |
| `tests/` | `unit/`(BE), `integration/db/`·`conftest.py`·`fixtures/raw/`(DB), `acceptance/`(QA) |

**이 작업은 이 폴더만 본다**
| 단계 | 쓰는 곳 |
|---|---|
| DB | `compose.yaml`, `src/lawqa/shared/db.py`, `src/lawqa/corpus/infrastructure/{schema.sql,pg_documents.py,pg_chunks.py,pg_index.py,vector_index.py}`, `src/lawqa/evaluation/infrastructure/files.py`, `tests/conftest.py`, `tests/fixtures/raw/`, `tests/integration/db/`, `docs/03-db/` |
| BE | 위 DB 파일을 뺀 `src/lawqa/**`(단 `entrypoints/streamlit_app.py` 제외), `config/`, `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`, `.gitignore`, `data/raw/.gitkeep`, `results/smoke/`(점검 출력), `tests/unit/`(단 `tests/unit/entrypoints/` 제외), `tests/fixtures/eval/`, `docs/04-backend/` |
| FE | `src/lawqa/entrypoints/streamlit_app.py`, `tests/unit/entrypoints/test_streamlit_app.py`, `README.md`, `docs/05-frontend/` |
| QA | `tests/acceptance/`, `docs/06-qa/` |
| 사람 | `data/raw/*.jsonl`, `data/MANIFEST.md`, `eval/*.json` 내용, `eval/SCHEMA.md`, `docs/problem.md`, `report.md`, `contributions.md`, `results/*/review.csv` 사람 판정, git 태그 |

공통 파일 담당: `.gitignore`·`.env.example`·`data/raw/.gitkeep`은 BE 골격 티켓, `compose.yaml`은 DB. 설계 문서: `docs/02-arch/HANDOFF.md`(티켓), `04-interfaces-api.md`(이름·명령·흐름), `03-db-schema.md`(표·파일 형식), `06-quality-gates.md`(명령·통과 기준).

# 개선안 v5 — 레드팀 공략안 + 구조 분석 통합

> 작성 2026-11-25 · 브랜치 `sanghyuk` · 근거: 「제12회 민사법 변형 공략안」(레드팀, 사용자 제공), `docs/analysis/structural-review.md`
>
> **기본 구성 = v5.** `configs/default.yaml` 의 `default_preset: v5` 라서 `eval`·`solve`·`solve-text`·화면에서 `--preset` 을 생략하면 v5 로 돈다. 예전 기본(v2) 결과를 재현하려면 `--preset v2` 를 붙이거나 이 값을 바꾼다. 실행 기록의 `run_meta.preset` 에 실제로 쓴 구성이 남는다.
>
> **v4 는 그대로다.** v4 실행이 진행 중이라 v4 프리셋을 바꾸면 같은 "v4" 결과가 서로 다른 코드에서 나온다. 새 기능은 v5 (와 `v5c`) 에서만 켜진다.

## 1. 두 문서의 겹침 정리

| 레드팀 공략 방향 | 구조 분석에서 겹치는 항목 | 하나로 합친 대응 | 상태 |
|---|---|---|---|
| **1. 선지 설계** — 오류 흡수 막기, 동점 유도, 개수형 | 확신도 보정 · 진술 일괄 판단 | ① 근소 차 재판단 ② 확신도 보정(도구) | ① v5 ② 도구만 (아래 §3) |
| **2. 코퍼스 경계** — 수집 안 한 법령, 판결요지만, 헌재 없음, 시점 혼재 | 시행령·특별법 · 법령 시점 · 판결 이유 | ③ 법령 12개 추가 ④ 법령 스냅숏 ⑤ 발문 기준 시점 ⑥ 색인 밖 법령 경고 | ③④ PC 수집 필요, ⑤⑥ v5 |
| **3. 리라이트가 지우는 사실** — 300/800자 밖, 세 번째 법리, 판례 짝 | (레드팀만) | ⑦ 리라이트 v4: 발문 전체 + 결정적 사실·금액/순서 법리 | v5 |
| **4. 진술 독립 판단** — 진술 간 전제, 진술별 가정 사실 | 진술 일괄 판단(부분) | ⑧ 진술 간 참조 질의 ⑨ 판단 v5 가정 사실 규칙 | v5 |
| **5. 이중부정·판례 변경 논거** | (v4 에서 일부) | ⑩ 판단 v5: 논거 분리, 반대의견·변경 전 판례는 판례 아님 | v5 (이중부정은 v4) |
| — | 인용 검증이 형식만 | ⑪ 인용 문장(quote) 대조, 실패 시 확신도 ×0.85 | v5 |
| — | 표본이 작음 | ⑫ `compare` (정확 McNemar) | 명령 |
| — | 통합 테스트 없음 · 색인 재현성 · 중단 실행 | ⑬ 프리셋별 끝까지 도는 테스트 ⑭ 색인 해시·스냅숏을 summary 에 ⑮ `complete` 표시 | 완료 |

레드팀 문서의 현재 상태 표기 중 **v4 에서 이미 바뀐 것**: 판례 선고일·전원합의체 표시(v4 `case_meta`), 동점 처리(v4 `tie_rejudge`), 발문 800자(v4) — v5 는 이를 넘어 발문 전체를 본다.

## 2. 구현 내용

| # | 기능 | 스위치 (v5 값) | 코드 |
|---|---|---|---|
| ① | **근소 차 재판단** — 2등 점수 ≥ 1등 × 0.5 이면 갈리는 진술만 근거와 다시 판단 (오답 보기를 진술 하나 차이로 둔 문항 대응) | `mcq.rejudge_ratio` (0.5) | `solver.py::_tiebreak`, `tied_options(ratio)` |
| ③ | 법령 추가: 상법 시행령, 소송촉진법, 이자제한법, 보증인보호법, 신탁법, 수표법, 약관규제법, 소액사건심판법, 전자증권법, 공탁법, 민사소송규칙, 민사집행규칙 | 문서 목록 | `data/documents.csv` |
| ④ | **법령 스냅숏** — 시험 시점 법령으로 따로 수집·색인 (`statutes@날짜/`, `index@날짜/`) | `--snapshot`, `corpus.statute_snapshot` | `config.py::index_path/raw_path`, `cli.py fetch-laws/build-index` |
| ⑤ | **발문 기준 시점** — "2023. 1. 1. 당시/현재/기준" → 그 날짜 이후 판례를 그 문항 검색에서 제외 | `mcq.asof_from_stem` | `defense.py::asof_date`, `pipeline.py::retrieve(date_to)` |
| ⑥ | **색인 밖 법령 경고** — 발문·진술의 ｢법령｣ 이 색인에 없으면 판단 입력에 경고, 판단 v5 는 비슷한 법령 조문으로 단정 금지 | `mcq.out_of_corpus_warn` | `defense.py::out_of_corpus` |
| ⑦ | **리라이트 v4** — 발문 전체(자르지 않음), 결론을 가르는 사실 우선, 금액·순서 법리 | `mcq.rewrite_version` ("v4"), `rewrite_stem_chars` (0=전체) | `prompts.py::MCQ_REWRITE_SYSTEM_V4` |
| ⑧ | **진술 간 참조 질의** — "ㄱ의 경우에 이어", "위 ㄴ에서" → 전제 진술 + 이 진술을 합친 질의 추가 | `mcq.cross_ref_queries` | `defense.py::cross_refs` |
| ⑨⑩ | **판단 v5** — 진술별 가정 사실 적용, 논거 문구 분리, 반대의견·변경 전 판례 배제, 색인 밖 법령 규칙, 인용 문장 출력 | `mcq.prompt_version` ("v5") | `prompts.py::MCQ_SYSTEM_V5` |
| ⑪ | **인용 대조** — `quote` 가 인용 청크에 그대로 있는지, 없으면 확신도 ×0.85 | `mcq.quote_check`, `quote_penalty` (0.85) | `solver.py::_check_quotes` |
| ⑫ | `kant-rag compare 실행A 실행B` — 문항별 교차표 + 정확 McNemar p | 명령 | `evaluate.py::compare_runs` |
| ② | `kant-rag calibrate 실행…` — 확신도 보정표 (단조, source 별) | `mcq.calibration` (v5 기본 꺼짐) | `defense.py::fit_calibration`, `Calibrator` |
| ⑬ | 통합 테스트: v3·v4·v5 로 한 문항을 끝까지 (가짜 검색기·LLM) | — | `tests/test_v5.py` |
| ⑭⑮ | summary 에 색인 청크 해시·스냅숏·판례 상한, `complete: true`, v5 집계(기준 시점·색인 밖 법령·진술 참조·인용 대조) | — | `evaluate.py`, `build_index.py` |
| — | `fetch-laws` 가 한 법령 실패(예: 대법원규칙 미지원)로 전체가 멈추던 문제 수정 → 경고 후 계속 | — | `cli.py fetch-laws` |

## 3. 미리 확인한 것 (PC 실행 없이, 기존 기록 재계산)

| 확인 | 결과 | 결정 |
|---|---|---|
| 확신도 보정표 (tune-b·tune-c 진술 462개로 생성) 를 점수 계산에 적용 | v2 58→57, tune-b 51→50, bar13 v3 65→64, bar13 closed-book 53→49, 변형본 66→65 | **v5 기본에서 제외.** 보정이 0.99 와 1.0 을 같은 값(0.98)으로 묶고 0.9 이하를 0.76 으로 낮춰 구별력을 잃었다. 표본이 더 쌓이면 `--set mcq.calibration=configs/calibration.json` 으로 비교 |
| 근소 차 재판단이 걸리는 문항 (2등 ≥ 1등×0.5) | tune-c 6/53 (그중 16·26·36 은 실제 오답), 변형본 4/70, bar13 3/70 | v5 에 유지 (문항의 약 10% 에서 LLM 1회 추가) |
| tune-b vs tune-c 대응 비교 | 51 vs 48, 한쪽만 정답 4:1, McNemar p = 0.375 | 단일 실행 차이로는 우열을 말할 수 없다 → 반복 실행 필요 |
| 테스트 | 78개 통과 (v5 신규 10개, 통합 3개) | |

## 4. 하지 않은 것 (이유)

| 항목 | 이유 | 대안 |
|---|---|---|
| 헌법재판소 결정 수집 | law.go.kr 헌재결정례 API 의 응답 구조를 확인하지 못함 (클라우드에서 API 접근 불가) | PC 에서 `api-check` 로 응답을 본 뒤 추가 |
| 판결 이유(판례내용) 청크 | 판례 31,079건 전체 재수집이 필요, 용량·시간 큼 | 필요한 판례만 골라 받는 방식으로 다음 단계에서 |
| 새 시험 봉인 | 데이터 운영 절차라 코드로 대신할 수 없음 | 제12회를 쓰기 전, 구성을 확정할 때까지 열지 않기 (레드팀 변형본은 v5 평가용) |
| 확신도 보정 기본 적용 | §3 재계산에서 성능 저하 | 도구만 제공 |

## 5. PC 에서 실행하는 순서

```bash
git pull origin sanghyuk
```

(1) 추가 법령 수집 → 색인 다시 만들기 (실패한 법령은 경고만 하고 넘어감)

```bash
uv run kant-rag fetch-laws --only 시행령 특례법 이자제한법 보증인 신탁법 수표법 약관 소액사건 전자등록 공탁법 민사소송규칙 민사집행규칙 사물관할
```
```bash
uv run kant-rag build-index
```

(2) v5 실행

```bash
uv run kant-rag eval data/exam/<시험 파일>.json --modes hybrid_rerank --preset v5 --label <라벨>
```

(3) 과거 시험을 그 시점 법령·판례로 (예: 2023년 1월 시험)

```bash
uv run kant-rag fetch-laws --snapshot 20221231
```
```bash
uv run kant-rag build-index --snapshot 20221231 --case-date-to 20221231
```
```bash
uv run kant-rag eval data/exam/<시험 파일>.json --modes hybrid_rerank --preset v5 --set corpus.statute_snapshot=20221231 --label <라벨>-asof
```

(4) 비교

```bash
uv run kant-rag compare results/<v4 실행> results/<v5 실행>
```

## 6. 판정 기준

- 구성 선택은 튜닝 세트(53문항) 반복 실행(`--repeat 3`) + `compare` 로. 정답 수와 함께 **확신 오답 수**, `v5.quote_check.failed`, `tiebreak` 결과를 본다.
- 레드팀 변형본(제12회 기반)은 v5 를 공격하는 평가용으로 쓰고, 그 결과를 보고 v5 를 다시 고치면 그 변형본은 더 이상 공정한 평가가 아니다 — 고친 뒤에는 새 변형본이 필요하다.

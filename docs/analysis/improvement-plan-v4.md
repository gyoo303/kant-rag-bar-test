# 개선안 v4 — 구현 내용과 실행 방법

> 작성 2026-11-25 · 브랜치 `sanghyuk` · 근거: `docs/analysis/report-bar13-v3.md`(bar13 오답·코드 리뷰), `docs/analysis/report-v2-vs-v3.md`
>
> **v3 는 그대로다.** 새 기능은 모두 스위치이고 기본값은 꺼져 있다. `--preset v3`(= `c`)와 `b` 는 이전과 똑같이 동작한다. 새 기능은 프리셋 `d`, `dc` 에서만 켜진다.

## 1. 무엇을 바꿨나

| # | 개선 | 대상 문제 | 스위치 (기본값) | 코드 |
|---|---|---|---|---|
| 1 | **번호 계산 예비 규칙** — 진술 판단 조합이 어느 보기와도 맞지 않아 모든 보기가 0점이면, 확신도 상한(0.95)으로 다시 계산해 "가장 적게·약하게 뒤집으면 맞는 보기"를 고른다. 상태 `inconsistent_judgments`, 뒤집은 진술(`answer_check.flipped`) 기록 | bar13 문 23 (동점 → ①) | `mcq.answer_fallback` (false) | `solver.py::choose_answer_robust` |
| 2 | **결과 요약 집계 추가** — 판단 불일치 문항·뒤집은 진술, 리라이트 실패 문항·진술·원인 | 리라이트 실패가 묻힘 (bar13 문 17·53) | 항상 (집계만) | `evaluate.py::_inconsistent`, `_rewrite_fallback` |
| 3 | **판례 선고일 상한 필터** — 이후 선고된 판례 청크를 검색 결과에서 제외 (조문은 그대로) | 과거 시험에 이후 판례가 근거로 쓰임 (bar13 문 23) | `retrieval.case_date_to` (없음) | `retrieval/pipeline.py::_date_filter` |
| 4 | **리라이트 v3** — 쟁점·예외 질의에 **사례 속 당사자 지위 질의**(party)를 더해 진술당 최대 3개. 발문을 800자까지 보여 준다 | 판례가 색인에 있는데 쟁점을 비켜 감 (bar13 문 38·65) | `mcq.rewrite_version` ("v2"), `rewrite_queries`, `rewrite_stem_chars` (300) | `prompts.py::MCQ_REWRITE_SYSTEM_V3` |
| 5 | **판례 메타 표시** — 근거 머리에 `decided="2024-07-18"`, 전원합의체면 `full_court="true"` (판결요지의 다수의견·반대의견 표시로 판별) | 옛 판례가 최신·전원합의체 판례를 덮음 (bar13 문 65) | `mcq.case_meta` (false) | `solver.py::_case_attrs`, `full_court_cases` |
| 6 | **판단 프롬프트 v3** — v2 + ⑥ 조문 요건과 사실관계 대조 ⑦ 판례 충돌 시 최신·전원합의체 우선 ⑧ 근거와 지식이 다르면 `[지식과 다름]` 표시 + 확신도 1.0 기준 | 조문 오적용 (2026 문 61), 판례 변경, 과잉 확신 | `mcq.prompt_version` ("v1") → "v3" | `prompts.py::MCQ_SYSTEM_V3` |
| 7 | **보강 수집 준비** — `fetch-cases --topics/--topics-file/--date-from/--per-topic/--out`, 문서 목록에 「민사 및 가사소송의 사물관할에 관한 규칙」 추가 | 근거 자체가 없음 (2026 문 35·36, bar13 문 27) | PC 에서 수집 후 `build-index` | `cli.py fetch-cases`, `data/cases/topics_added.txt`, `data/documents.csv` |

### 프리셋

| 프리셋 | 구성 |
|---|---|
| `b` | v3 의 근거 확장 + 판단 프롬프트 v2 (튜닝 세트 최고 51/53) |
| `c` = `v3` | `b` + 유보 진술 지식 결합 |
| **`d`** | `b` + 1·4·5·6 (번호 계산 예비 규칙, 리라이트 v3 질의 3개, 판례 메타, 판단 프롬프트 v3) |
| **`dc`** | `d` + 유보 진술 지식 결합 |

날짜 필터(3)는 프리셋에 넣지 않았다. 과거 시험을 풀 때만 `--set retrieval.case_date_to=YYYYMMDD` 로 켠다.

## 2. 미리 확인한 것 (PC 실행 없이)

- 테스트 60개 통과 (`tests/test_v4.py` 7개 추가: 예비 규칙, 판례 메타, 리라이트 v3 파싱, 날짜 필터, 프리셋에서 v3 불변).
- **예비 규칙(1)을 기존 6개 실행 기록에 적용**한 결과: 바뀐 문항은 bar13 v3 문 23 하나(① → ④, 정답)뿐이다. 2026 v2·b·c·closed-book, bar13 closed-book 은 변화 0. 튜닝 세트에는 "모든 보기 0점" 문항이 없어 튜닝 점수는 그대로다. 성능 튜닝이 아니라 망가진 경우를 막는 안전장치다.
- 확신도 상한을 **항상** 적용하는 방식은 기각했다. 2026 v2 58 → 57 처럼 정상 문항까지 바뀌었다.

## 3. PC 에서 실행하는 순서

진행 중인 v3 실행이 끝나고 결과를 푸시한 **다음에** 한다.

```bash
git pull --no-edit origin sanghyuk
```

(선택) 데이터 보강 — 수집 후 색인을 다시 만들어야 반영된다.

```bash
uv run kant-rag fetch-laws --only 사물관할
```
```bash
uv run kant-rag fetch-cases --topics-file data/cases/topics_added.txt --date-from 19900101 --per-topic 5 --out data/raw/cases/cases_added.jsonl
```
```bash
uv run kant-rag build-index
```

`fetch-laws` 가 사물관할 규칙(대법원규칙)을 찾지 못하면 그 줄만 건너뛰고 진행해도 된다(색인은 없는 파일을 빼고 만든다).

튜닝 세트로 v4 효과 확인 (한 번에 하나씩):

```bash
uv run kant-rag eval data/exam/2026_civil_tune.json --modes hybrid_rerank --preset d --label tune-d
```
```bash
uv run kant-rag eval data/exam/2026_civil_tune.json --modes hybrid_rerank --preset dc --label tune-dc
```

bar13 을 시험 시점 법리로 다시 풀기 (선택, 날짜 필터):

```bash
uv run kant-rag eval data/exam/bar13_civil.json --modes hybrid_rerank --preset d --set retrieval.case_date_to=20231231 --label bar13-d-asof
```

## 4. 판정 기준과 주의

- **채택 기준은 튜닝 세트(53문항)만**: `d` 가 `b`(51)보다 높거나 같고, 확신 오답(진술)이 늘지 않으면 채택. 반복 2~3회로 변동 범위를 같이 본다.
- **데이터 보강(7)을 하면 bar13 재실행은 "보강 후" 결과로 따로 표시한다.** 보강 주제어 중 일부(가액배상 지연손해금)는 bar13 오답 분석에서 나왔기 때문에, 보강 후 bar13 점수는 처음 본 시험의 점수가 아니다. 2026 test 문항은 보강 근거로 쓰지 않았다.
- 프롬프트 예시는 평가 문항(2026 test·bar13)과 무관한 일반 사례로 넣었다.
- 리라이트 v3 는 질의가 진술당 3개라 검색이 약 1.5배 늘어 문항당 시간이 늘 수 있다.
- 남은 일(코드로 대신할 수 없음): 반복 실행, `eval/test.json` 고정(`frozen: true`) 후 최종 실행, 근거 적합 사람 채점(`grading.csv`).

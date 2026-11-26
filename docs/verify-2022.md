# verify-2022 브랜치 — 2022년 시험 전 판례만으로 검증

> 브랜치 `verify-2022` (sanghyuk 에서 분기, v6 포함). 2022년 변호사시험(제11회, 2022. 1. 11. 시작)을 **그 시점까지 선고된 판례만** 가지고 푼다.

## 이 브랜치에서 바뀐 것 (`configs/default.yaml`)

| 설정 | 값 | 뜻 |
|---|---|---|
| `paths.index_dir` | `index-2022` | 2022 색인을 따로 만든다. 현재 색인 `index/` 는 그대로 |
| `corpus.case_date_to` | `20220110` | 색인할 때 이 날짜 뒤 선고 판례 제외 |
| `retrieval.case_date_to` | `20220110` | 검색 단계에서 한 번 더 제외 (안전장치) |
| `mcq.asof_default` | `20220110` | 발문에 기준 시점이 없으면 이 날짜 기준 |
| `mcq.hide_future` | `true` | 이 날짜 뒤 판례는 근거 표시(판례 변경 `overruled_by`)에서도 숨김 |

연결 지도(v6)는 색인에 있는 판례만 잇고, 그 뒤 판례가 붙인 참조판례·참조조문 연결은 색인에 없으므로 쓰이지 않는다.
단위 테스트는 `tests/conftest.py` 가 위 값을 끈 설정으로 돌린다 (`tests/test_verify2022.py` 가 이 브랜치 설정을 확인).

## 한계

- **법령은 현재(2026) 버전**이다. 2022년 이후 개정된 조문이 쟁점이면 틀릴 수 있다. 시점 법령까지 맞추려면 아래 '선택' 참고.
- **LLM(gpt-6-luna)은 2022년 뒤 판례를 학습했을 수 있다.** 근거는 막아도 모델 기억은 막지 못한다. 근거 없이 판단한 진술(`source=knowledge`·인용 없음)을 따로 보아야 한다.

## PC 실행

```
git fetch origin
git checkout verify-2022
git pull
uv run pytest -q
uv run kant-rag build-index
```
- `index-2022/` 에 새 색인을 만든다. 이 세션 원자료 기준 판례 청크 36,087개 (현재 기준 39,268개의 92%, 가장 늦은 선고 2021-12-30). GPU 임베딩 수십 분.
- 끝나면 `index-2022/index_info.json` 의 `case_date_to` 가 `20220110` 인지 확인.

시험지·정답 넣기 (파일 이름은 예시):
```
uv run kant-rag import-exam data/exam/bar11_civil.txt --answers data/exam/bar11_civil_answers.csv --exam bar11 --prefix BAR11-CIV
```

풀기·채점:
```
uv run kant-rag eval data/exam/bar11_civil.json --modes hybrid_rerank --preset v6 --workers 1 --label bar11-v6-2022
uv run kant-rag regrade results/<실행 폴더> --exam data/exam/bar11_civil.json
```

작업이 끝나면 `git checkout sanghyuk` 로 돌아간다 (색인 폴더가 달라 서로 덮어쓰지 않는다).

## 선택: 2022년 시점 법령까지

```
uv run kant-rag fetch-laws --snapshot 20220110
uv run kant-rag build-index --snapshot 20220110
```
그 뒤 `configs/default.yaml` 의 `corpus.statute_snapshot` 을 `"20220110"` 으로 두고 eval 을 실행한다 (색인 폴더 `index-2022@20220110`).

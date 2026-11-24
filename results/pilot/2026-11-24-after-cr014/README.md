# CR-012~017 반영 후 재측정 — **진행 중 (34/70)**

> **미완성 기록이다.** 2026-11-24 17:27~17:45에 34문항까지 실행하고 멈췄다.
> 남은 36문항(35~70)은 아래 명령으로 **이어서** 돌리면 된다.

## 실행 조건 (이전 사전 실험과 다른 점)

| 항목 | 이전(`../2026-11-24/`) | 이번 |
|---|---|---|
| 프롬프트 | 시험 전용(번호 강제) | **운영 프롬프트** (CR-013·014 반영) |
| `max_tokens` | 2000 | **없음** (CR-012) |
| 생성 시간 제한 | 60초 | **90초** (CR-017) |
| 기권 | 있음(`INSUFFICIENT_EVIDENCE`) | **없음** — 번호 항상 제시 + `evidence_sufficient` (CR-014~016) |

구성 C+R, 색인 `idx-e7e52477-f86ae9e9`(청크 54,969), 모델 `gpt-6-luna`.

## 중간 상태 (34문항)

- 결과 종류: `ANSWERED` 34건 (오류·형식 실패 **0건**)
- 근거 충족 표시: 21/34
- 문항당 평균 31.2초
- 끝난 번호: 1~34 / 남은 번호: 35~70

**채점은 아직 하지 않았다.** 70문항이 다 끝난 뒤 `repro/grade_two.py`로 지표 2종을 낸다.

## 이어서 돌리기

실행 스크립트는 `run.jsonl`에 기록된 번호를 읽어 **끝난 문항은 건너뛴다.** 같은 명령을 그대로 다시 쓰면 된다.

```powershell
.venv\Scripts\python.exe results\pilot\2026-11-24-after-cr014\repro\run_exam.py results\pilot\2026-11-24-after-cr014\items.json results\pilot\2026-11-24-after-cr014\run.jsonl "C+R"
```

남은 36문항은 평균 31초 기준 **약 19분** 걸린다.

## 끝난 뒤 채점

```powershell
.venv\Scripts\python.exe results\pilot\2026-11-24-after-cr014\repro\grade_two.py results\pilot\2026-11-24-after-cr014\run.jsonl results\pilot\2026-11-24-after-cr014\items.json results\pilot\2026-11-24\graded.json
```

지표 2종(CR-014)과 이전 실행 대비 before/after가 함께 나온다.

- **① 정답 충족(번호)**: 고른 번호가 정답이면 1
- **② 근거 충족 정답**: 번호도 맞고 `evidence_sufficient=true`여야 1
- **격차(①−②)**: 맞혔지만 근거를 못 댄 문항 수

## 무결성

풀이 단계는 정답표(DOC-05)를 읽지 않는다. 채점 스크립트에서만 연다.
이 폴더는 색인 대상이 아니다(`corpus import`는 `law_collector/data/`만 읽는다).

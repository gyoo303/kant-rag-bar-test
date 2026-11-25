# CR-018·019·020 반영 후 재측정 — **진행 중**

> 세 개선(조문 몫 보장 / 2차 검색 / 명제 단위 질의 분해)이 모두 켜진 상태의 70문항 측정이다.
> 완료 전까지 이 수치를 결론으로 쓰지 말 것.

## 실행 조건

| 항목 | 값 |
|---|---|
| 구성 | C+R (리라이트 → BM25+벡터 → 재정렬 → 생성) |
| 색인 | `idx-e7e52477-f86ae9e9` (문서 40,096 / 청크 54,969) |
| 코드 | 커밋 `372210d` (CR-009~020 전부 반영) |
| `k_law` | 1 (CR-018 조문 몫) |
| 생성 시간 제한 | 90초 (CR-017), `max_tokens` 없음 (CR-012) |
| 질의 분해 | 조합형은 명제 단위 (CR-020) |
| 2차 검색 | 근거 부족 시 해당 명제만 재검색, 근거 충족일 때만 채택 (CR-019) |

## 이어서 돌리기

실행 스크립트가 `run.jsonl`의 번호를 읽어 끝난 문항을 건너뛴다. 같은 명령을 다시 쓰면 된다.

```powershell
.venv\Scripts\python.exe results\pilot\2026-11-25-cr018-020\repro\run_exam.py results\pilot\2026-11-25-cr018-020\items.json results\pilot\2026-11-25-cr018-020\run.jsonl "C+R"
```

## 끝난 뒤 채점

```powershell
.venv\Scripts\python.exe results\pilot\2026-11-25-cr018-020\repro\grade_two.py results\pilot\2026-11-25-cr018-020\run.jsonl results\pilot\2026-11-25-cr018-020\items.json results\pilot\2026-11-24-after-cr014\graded_two.json
```

## 무결성

풀이 단계는 정답표(DOC-05)를 읽지 않는다. 채점 스크립트에서만 연다.
이 폴더는 색인 대상이 아니다(`corpus import`는 `law_collector/data/`만 읽는다).

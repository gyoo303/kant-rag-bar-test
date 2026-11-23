# 평가셋 — 2026 변호사시험 민사법 선택형

| 파일 | 구성 (발제 기준) |
| --- | --- |
| `eval/dev.json` | 선택형 8 + 근거 없음 2 = 10 — 개발·튜닝용 (근거 부족 판정 임계값도 여기서만 정함) |
| `eval/test.json` | 선택형 17 (`direct` 10 + `paraphrase` 7) + 근거 없음 3 = 20 — **최종 평가 전용**, 실행 전 `frozen: true` |
| `data/exam/2026_civil_extra.json` | 나머지 45문항 — 최종 결과 이후 추가 실험용 (본 평가와 분리 보고) |

생성 절차는 `data/exam/README.md` 참고 (`import-exam` → `split-exam`). 지금은 문항이 비어 있습니다.

## 선택형 문항 (`items`)
```jsonc
{
  "id": "BAR2026-CIV-012", "number": 12, "subject": "민법",
  "stem": "불법행위에 관한 설명 중 옳지 않은 것은? (다툼이 있는 경우 판례에 의함)",
  "items": {},                          // 조합형/개수형이면 {"ㄱ": "...", "ㄴ": "..."}
  "options": {"1": "...", "2": "...", "3": "...", "4": "...", "5": "..."},
  "answer": 3,                          // 법무부 확정 정답 — 풀이 입력에는 절대 들어가지 않음
  "type": "direct",                     // direct: 조문 직접 확인 / paraphrase: 사례·표현 변형·유사 조건 구분
  "evidence": [                         // 허용 근거 (Hit@5): 어느 진술의 top-5 에든 있으면 1
    {"doc_id": "LAW-CIVIL", "chunk_id": "LAW-CIVIL#제766조", "location": "민법 제766조 제1항"}
  ],
  "statement_labels": {"1": true, "2": true, "3": false, "4": true, "5": true},  // 선택: 진술별 정오
  "split": "test"
}
```
- 발문의 극성(옳은 것/옳지 않은 것)과 형식(단일/조합/개수)은 발문에서 자동 판별됩니다 (`mcq/schemas.py`).
- 법령 청크 ID 는 조문 번호 기반(`LAW-CIVIL#제766조`)이라 청킹 크기를 바꿔도 유지됩니다. 긴 조문은 `-1`, `-2` 로 나뉩니다.
- **판례로만 답이 정해지는 진술**은 판례 문서를 색인하지 않았다면 evidence 를 비우고(Hit@5 분모에서 제외) note 로 남깁니다.

## 근거 없음 문항 (`no_answer`) — 팀이 직접 작성
색인 범위(수집한 법령·판례)로 답할 수 없는 질문. 예시 방향:
- 색인하지 않은 법령 질문 (예: 수집하지 않은 특별법의 세부 요건)
- 시험일 이후 개정 내용을 묻는 질문
```jsonc
{"id": "DEV-NA-01", "split": "dev", "type": "no_answer", "question": "...",
 "expected_facts": [], "reference_answer": "정보 부족 안내", "evidence": [],
 "no_answer_reason": "색인 범위에 해당 법령이 없음"}
```

## 규칙
- 시험 문제·정답·해설을 색인(`data/raw`)이나 프롬프트에 넣지 않습니다.
- 최종 평가 문항은 개발·튜닝에 쓰지 않고, 결과를 본 뒤 교체하지 않습니다.
- `uv run kant-rag check-eval` 로 구성을 검사합니다.

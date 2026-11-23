# 평가셋 스키마

| 파일 | 문항 | 구성 |
| --- | --- | --- |
| `eval/dev.json` | 10 | 답변 가능 8 (`direct`/`paraphrase`) + 근거 없음 2 (`no_answer`) — 개발·튜닝용 |
| `eval/test.json` | 20 | 직접 검색 10 (`direct`) + 표현 변형·유사 조건 7 (`paraphrase`) + 근거 없음 3 (`no_answer`) — **최종 평가 전용** |

현재 `dev.json` 에는 샘플 문서 기준 예시 2문항만 들어 있습니다. 실제 문서로 교체하면서 채워 주세요.

## 필드

```jsonc
{
  "version": "eval-v0.1",        // 평가셋 버전 (configs/default.yaml versions.eval 과 맞춤)
  "split": "dev" | "test",
  "frozen": false,                // test 는 최종 실행 전 true 로 고정 → 이후 수정 금지 (git 태그로 고정)
  "items": [{
    "id": "TEST-01",              // 질문 ID (dev/test 간 중복 금지)
    "split": "test",
    "type": "direct" | "paraphrase" | "no_answer",
    "question": "...",
    "expected_facts": ["..."],    // 정답 충족 판정용 필수 핵심 사실 (모두 맞아야 1)
    "reference_answer": "...",    // 기대 답변 (근거 없음 문항은 "정보 부족 안내")
    "evidence": [                 // 허용 근거 — 하나라도 최종 top-5 에 있으면 Hit@5 = 1
      {"doc_id": "...", "chunk_id": "...", "location": "§ ... / L.."}
    ],
    "no_answer_reason": null      // 근거 없음 문항: evidence 를 비우고 부재 판정 이유 기록
  }]
}
```

## 규칙
- 청킹 설정을 바꿔 chunk_id 가 바뀌면 `uv run kant-rag chunks` 로 새 ID 를 확인해 `evidence` 를 갱신하고, `versions.index` 를 올립니다.
- 평가 정답표는 검색 색인(`data/raw`)이나 프롬프트에 넣지 않습니다.
- `uv run kant-rag check-eval` 로 스키마·문항 구성을 검사합니다.

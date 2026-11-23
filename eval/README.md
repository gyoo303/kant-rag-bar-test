# 평가셋

| 파일 | 문항 | 구성 | 용도 |
|---|---|---|---|
| `dev.json` | 10 | 답변 가능 8 + 근거 없음 2 | 개발·튜닝 (기출 기반) |
| `test.json` | 20 | 직접 검색 10 + 표현 변형·유사 조건 7 + 근거 없음 3 | **최종 평가 전용** (변형 시험, 튜닝 금지) |

- `test.json`은 최종 평가 실행 **전에** 버전을 고정하고(`version` 필드 + git 태그), 이후 수정하지 않는다.
- 정답표·평가셋 내용을 검색 색인이나 프롬프트에 넣지 않는다.
- 청킹을 바꿔 청크 ID가 달라지면 `allowed_evidence`를 갱신하고 버전을 다시 고정한다.
- 기출 문제 출처(회차·문항 번호)는 기록하되, 출판사 해설 원문은 넣지 않는다.

## 스키마
```json
{
  "version": "test-v1",
  "items": [
    {
      "id": "T01",
      "type": "direct | paraphrase | no_evidence",
      "question": "질문 원문 (OX 또는 서술형)",
      "expected_answer": "O | X | 서술형 정답 요지",
      "expected_facts": ["필수 핵심 사실 1", "핵심 사실 2"],
      "allowed_evidence": [
        {"doc_id": "판례일련번호", "case_no": "2020다12345", "section": "판결요지", "chunk_id": "…"}
      ],
      "source": "제○회 변호사시험 민사법 선택형 ○번 지문 ③ (변형)",
      "no_evidence_reason": "근거 없음 문항일 때만: 왜 코퍼스에 근거가 없는지"
    }
  ]
}
```

- `type = no_evidence` 문항: `expected_answer = "정보 부족 안내"`, `allowed_evidence = []`
- `chunk_id`는 색인 후 채운다. 그 전까지는 `doc_id`·`section`으로 매핑해 둔다.

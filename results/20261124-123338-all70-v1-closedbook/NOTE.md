# NOTE

응답 파싱 버그(Extra data)·출력 한도(빈 응답)로 오류 발생 — 909d0c0 에서 수정, 성능 결과에서 제외

- 세부: 15/70 에서 수동 중단(summary.json 없음), generation_error 6건(ValueError: JSON 응답 없음, raw_output 빈 응답).

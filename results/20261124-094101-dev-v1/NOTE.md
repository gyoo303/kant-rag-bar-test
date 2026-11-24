# NOTE

설정 오류(API 키 없음)로 모델 미호출 — 성능 결과에서 제외

- 세부: OPENAI_API_KEY 에 OpenAI 키가 아닌 값이 들어 있어 모든 호출이 401 인증 오류로 실패 (generation_error 28건). 정답 0건은 모델 성능이 아님.

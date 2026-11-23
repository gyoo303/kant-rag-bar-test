# 실행 결과

실행마다 `results/<run_id>/` 폴더를 만들고 아래를 남긴다. 실패·재시도·워밍업도 지우지 않고 표시한다.

```
results/<run_id>/
  config.json     구성(A/B/C/C+rewrite), 문서·색인·모델·프롬프트 버전, k·가중치
  runs.jsonl      문항별 1줄: question_id, 후보·점수, 재정렬 전후 순위, 원본 답변, 출처,
                  응답 시간, 상태(ok / no_evidence / error / timeout)
  scores.csv      문항별 채점: hit@5, 정답 충족, 근거 적합, 근거없음 대응, 채점 근거, 채점자
  summary.md      지표 합계(분모 포함)·응답 시간 평균/중앙값(n)·오류 수
```

`run_id` 예: `20261127-test-v1-C` · 본 평가(60건)와 추가 실험(리라이트 20건, Agentic)은 폴더 이름으로 구분.

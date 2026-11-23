# 시험지 (팀 계획 1단계: 기본 변호사시험 점수 최대화)

시험지 1회분 = JSON 파일 1개. 형식은 [sample_format.json](sample_format.json) 참고 (실제 기출 아님).

```json
{
  "exam_id": "2025-civil-mc",            // 결과 폴더 이름에 쓰임
  "title": "제14회 변호사시험 민사법 선택형",
  "source": "법무부 공개 기출",
  "items": [
    {
      "no": 1,
      "subject": "민법",                  // 민법 | 상법 | 민사소송법 — 과목별 정답률 집계
      "stem": "…에 관한 설명으로 옳지 않은 것은?",
      "passage": "(사례형이면 사례 지문, 없으면 생략)",
      "choices": {"1": "…", "2": "…", "3": "…", "4": "…", "5": "…"},
      "answer": 3,                       // 정답 번호 (모르면 생략 → 채점 안 함)
      "evidence": ["판례일련번호 또는 law:민법:750 (선택)"]
    }
  ]
}
```

## 풀기
```powershell
uv run civil-rag exam exams/2025-civil-mc.json --configs LLM A B C C+RW
uv run civil-rag exam exams/2025-civil-mc.json --configs C --strategy per_choice
uv run civil-rag exam exams/2025-civil-mc.json --configs C --numbers 3 7 12    # 특정 문항만
```
- `whole`: 문제 전체로 한 번 검색 → 정답 번호 선택 (빠름)
- `per_choice`: 보기마다 검색·O/X 판단 → 발문(옳은/옳지 않은)에 맞춰 선택 (느리지만 보기별 근거가 정확)
- 결과: `results/<시각>-exam-<exam_id>/compare.md` (점수 비교), 구성별 `summary.md` · `answers.csv` · `runs.jsonl`

## 주의
- 기출 문제·정답은 법무부 공개 자료. **출판사 해설은 넣지 않는다** (저작권).
- 2단계 변형 시험(최종 평가셋)은 1단계에서 튜닝에 쓰지 않도록 **이 폴더가 아니라 `eval/test.json`** 에 따로 둔다.
- 시험 범위에 상법·민사소송법이 있으면 `law_collector/collect.py laws 상법 민사소송법` 으로 조문을 받아 재색인해야 근거가 생긴다.

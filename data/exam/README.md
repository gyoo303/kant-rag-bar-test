# 시험 문항 (평가 입력 전용 — 색인 금지)

2026년 제15회 변호사시험 선택형 **민사법 70문항** (출처: 법무부 공개 문제)

1. 법무부 공개 문제를 텍스트로 저장: `data/exam/2026_civil.txt`
   - PDF/HWP/뷰어에서 복사한 그대로 두면 됩니다. 문항은 행 시작의 `문  1.`(2026 시험지 형식) 또는 `【문 1】`, 보기는 `①~⑤`, 조합형 진술은 `ㄱ.~ㅁ.`
   - 법무부 사이트(moj.go.kr)는 클라우드 세션에서 접속이 차단되므로 PC 브라우저에서 내려받아 넣습니다. 쪽 번호(`1쪽`)·과목 표제는 자동 제거됩니다.
2. 확정 정답을 저장: `data/exam/2026_civil_answers.csv` (`number,answer` — 예: `1,3`)
3. 변환: `uv run kant-rag import-exam data/exam/2026_civil.txt --answers data/exam/2026_civil_answers.csv`
   → `data/exam/2026_civil.json` (70문항). 파싱 결과는 반드시 원본과 대조해 고치세요.
4. 평가셋 분리: `uv run kant-rag split-exam data/exam/2026_civil.json` → `eval/dev.json`(선택형 8) / `eval/test.json`(선택형 17)
   - 근거 없음 문항(dev 2 / test 3)은 팀이 직접 작성해 `no_answer` 에 추가
   - 나머지 45문항은 `data/exam/2026_civil_extra.json` — 최종 결과 확인 뒤 추가 실험으로만 사용 (본 평가와 분리 보고)

# 시험 문항 (평가 입력 전용 — 색인 금지)

2026년 제15회 변호사시험 선택형 **민사법 70문항** (출처: 법무부 공개 문제)

1. 법무부 공개 문제를 텍스트로 저장: `data/exam/2026_civil.txt`
   - PDF/HWP/뷰어에서 복사한 그대로 두면 됩니다. 문항은 행 시작의 `문  1.`(2026 시험지 형식) 또는 `【문 1】`, 보기는 `①~⑤`, 조합형 진술은 `ㄱ.~ㅁ.`
   - 법무부 사이트(moj.go.kr)는 클라우드 세션에서 접속이 차단되므로 PC 브라우저에서 내려받아 넣습니다. 쪽 번호(`1쪽`)·과목 표제는 자동 제거됩니다.
2. 확정 정답을 저장: `data/exam/2026_civil_answers.csv` (`number,answer` — 예: `1,3`)
   - 이미 분리한 뒤라면 `uv run kant-rag apply-answers data/exam/2026_civil_answers.csv` 로 문항·평가셋에 일괄 반영
3. 변환: `uv run kant-rag import-exam data/exam/2026_civil.txt --answers data/exam/2026_civil_answers.csv`
   → `data/exam/2026_civil.json` (70문항). 파싱 결과는 반드시 원본과 대조해 고치세요.
4. 평가셋 분리: `uv run kant-rag split-exam data/exam/2026_civil.json` → `eval/dev.json`(선택형 8) / `eval/test.json`(선택형 17)
   - 근거 없음 문항(dev 2 / test 3)은 팀이 직접 작성해 `no_answer` 에 추가
   - 나머지 45문항은 `data/exam/2026_civil_extra.json` — 최종 결과 확인 뒤 추가 실험으로만 사용 (본 평가와 분리 보고)

## 다른 시험지: `bar13_civil` (사용자 제공 hwpx, 70문항)
- 원본 `.hwpx` 는 커밋하지 않고, 본문 XML 에서 추출한 텍스트(수정 추적의 삭제분 제외)를 `bar13_civil.txt` 로 저장 → `bar13_civil.json`
- 과목: 민법 35 · 상법 19 · 민사소송법 16 (문항 내용으로 분류, 통합형 문항 32·34~36·65·69 는 상법으로 표기)
- 정답: 사용자 제공 답지(hwp)에서 추출 → `bar13_civil_answers.csv` (70문항, 문 1·69·70 지문 대조 확인)
- 2026 시험의 dev/test 분리와 무관한 외부 시험 (split=external) — 설정 튜닝에 쓰지 않고 일반화 확인용

## 레드팀 변형본: `bar12_adv` (제12회·2023 기반, 70문항, 정답 미입력)
- 사용자 제공 텍스트 → `bar12_adv.txt` → `bar12_adv.json` (단일 47 · 조합 11 · 개수 7 · ○× 4 · **괄호 넣기 1**)
- 새 형식 지원: 개수형 보기에 "알 수 없음"(문 12), 괄호 넣기형(문 56: 빈칸마다 후보 값을 넣은 문장을 각각 판단)
- 먼저 정답 없이 풀고(`eval`), 정답을 받은 뒤 `bar12_adv_answers.csv` 로 다시 변환해 `kant-rag regrade` 로 채점한다

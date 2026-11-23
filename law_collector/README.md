# 민사 판례·법령 수집기 (open.law.go.kr)

팀원 3명이 **각자 자기 OC로, 하루 10,000회 이내**에서 민사 판례를 나눠 받는 스크립트입니다.
Python 3.9 이상만 있으면 되고, `pip install` 할 것은 없습니다.

## 0. 각자 준비 (팀원 모두)
1. https://open.law.go.kr 회원가입 → **OPEN API 신청**
   - OC: 본인이 정하는 아이디
   - 서버장비 IP: **수집을 돌릴 PC의 공인 IP** (`Invoke-RestMethod https://api.ipify.org` 로 확인)
   - 법령종류: 대한민국 현행법령, 판례 → 목록/본문 XML·JSON 체크
2. 이 폴더를 받은 뒤 `.env.example` 을 `.env` 로 복사하고 `LAW_OC=` 에 본인 OC 입력

> OC는 인증키입니다. `.env` 는 git 에 올리지 마세요 (`.gitignore` 에 이미 포함).

## 1. 민사 판례 ID 목록 만들기 — `list`
```
python collect.py list
```
- 전체 판례(약 17.6만 건)를 100건씩 약 1,760회 훑어서 **민사(사건종류코드 400101)만** `data/civil_ids.jsonl` 에 저장
- **한 명(팀장)만** 돌리고 `data/civil_ids.jsonl` 을 팀에 공유(git 커밋 등)하면 나머지는 이 단계 생략
- 각자 돌려도 됩니다. 분담 기준이 판례일련번호라서 결과가 같습니다.

> ✅ 이미 완료됨 (2026-11-23): 민사 52,333건 → `data/civil_ids.jsonl` 에 들어 있음. **팀원은 이 단계 건너뛰기.**

## 2. 내 담당 본문 받기 — `fetch` (매일 실행)
팀 약속: **데이터출처 "대법원" 만** 받기 (42,537건, 1인 약 14,200건 → 하루 10,000건씩 2일)
```
python collect.py fetch --member 1 --source 대법원     # 팀원 1
python collect.py fetch --member 2 --source 대법원     # 팀원 2
python collect.py fetch --member 3 --source 대법원     # 팀원 3
```
- 담당 = `판례일련번호 % 3` → 세 명 범위가 절대 겹치지 않음
- 하루 10,000회에 닿으면 자동 종료 → **다음 날 같은 명령을 다시 실행**하면 이어서 받음
- 중간에 Ctrl+C·정전·오류로 끊겨도 저장된 건 건너뛰고 이어서 진행
- 시험 삼아 몇 건만: `--limit 5` (예: `python collect.py fetch --member 2 --source 대법원 --limit 5`)

## 3. 법령 조문 받기 — `laws` (한 명만)
```
python collect.py laws               # 민법·민사소송법·민사집행법·상법 등 기본 목록
python collect.py laws 민법 신탁법    # 원하는 법만
```

## 진행 상황
```
python collect.py status
```

## 결과 합치기
각자 `data/prec/*.json` 을 공유 폴더 하나에 모으면 끝입니다. 파일명이 판례일련번호라 겹치지 않습니다.

## 폴더 구조
```
data/civil_ids.jsonl   민사 판례 ID 목록 (공유용)
data/prec/{ID}.json    판례 본문 (판시사항·판결요지·참조조문·참조판례·판례내용 …)
data/law/{법령명}.json  법령 본문
state/                 호출 카운터·진행 상황·실패 기록 (개인용)
```

## 설정 (`.env`)
| 키 | 기본값 | 설명 |
|---|---|---|
| `LAW_OC` | – | 본인 OC (필수) |
| `DAILY_LIMIT` | 10000 | 하루 최대 호출 수 |
| `REQUEST_DELAY` | 0.5 | 요청 간격(초). 10,000건 ≈ 2시간 남짓 |
| `MEMBERS` | 3 | 팀원 수 |

## 자주 나는 오류
- **사용자 인증 실패** → OC 오타 또는 지금 PC의 공인 IP가 등록 IP와 다름. open.law.go.kr 마이페이지 > API인증키관리에서 수정
- **10건 연속 실패** → 네트워크·서버 문제. 잠시 후 재실행
- 본문에는 `<br/>` 같은 HTML 태그가 섞여 있으니 전처리 때 제거

출처 표기: 법제처 국가법령정보센터

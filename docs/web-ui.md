# 웹 채팅 화면 (민사법 AI · KANTNYANGI)

기존 엔진(`KnowledgeAgent`, `MCQSolver`)을 그대로 호출하는 채팅 화면이다. 검색·판정·프롬프트·평가 코드는 바꾸지 않았다.

## 실행

```
uv sync
uv run kant-rag-web            # http://127.0.0.1:8600
```

`.env` 와 `configs/default.yaml`(또는 `KANT_RAG_CONFIG`)의 설정·색인을 그대로 쓴다. 첫 질문 때 색인·리랭커를 불러오느라 1~2분 걸린다.

## 구성

| 파일 | 역할 |
|---|---|
| `src/kant_rag/web/api.py` | API 서버 (FastAPI). 엔진 결과를 화면용 JSON 으로만 바꾼다 |
| `app/web/index.html` · `styles.css` · `app.js` | 화면 (빌드 도구 없음). 디자인 토큰은 `styles.css` 맨 위 `:root` |
| `app/web/assets/` | 브랜드 에셋 — 칸트 초상·월계수는 팀 배너에서 잘라냄, 고양이 3종·배너는 팀 원본 |
| `app/web/team.json` | 팀 소개 문구와 팀원 이름·역할 (**이름·역할은 비어 있음 — 채워 넣을 것**) |
| `tests/test_web_api.py` | API 변환·상태 구분 테스트 (가짜 엔진, 색인·LLM 불필요) |

## API

| 경로 | 내용 |
|---|---|
| `GET /api/config` | 고를 수 있는 답변 모델·검색 방식·풀이 프리셋, 기준일 |
| `POST /api/chat` | `{text, model, mode, preset, intent}` → 보기(①~⑤)가 있으면 기출 풀이(`MCQSolver.solve`), 아니면 질의응답(`KnowledgeAgent.ask`) |

- 답변 모델 기본값은 `.env` 의 `LLM_PROVIDER`/`LLM_MODEL` (평가와 같은 모델). 비교용 모델은 `WEB_MODEL_OPTIONS=openai:모델,anthropic:모델` 로 추가하며, 서버에 그 공급자 키가 없으면 목록에 나오지 않는다. 평가 CLI 는 이 설정을 쓰지 않는다.
- 상태는 `status_kind` 로 구분한다: `ok` · `insufficient`(근거 부족) · `error`(검색·생성·시스템 오류). 오류 문구의 키 형태 문자열은 가린다.
- 색인이 없거나 미완성이면 엔진의 안내(`build-index` 실행)를 `code: "setup"` 오류로 돌려주고, 화면은 '검색 색인이 준비되지 않았어요'로 보여 준다. 서버는 꺼지지 않는다.
- 근거(`docs`)는 색인 청크에 있는 값만 쓴다: 사건번호·선고일·항목, 조문 번호·제목·시행일, 원문. 원문 링크는 판례 일련번호(prec_id)와 법령명·조문으로 만든 국가법령정보센터 주소.

## 질의응답 (화면 전용 보강)

질의응답은 엔진 함수(쿼리 리라이트 `rewrite_query`, 검색 `Retriever.retrieve`, 답변 `generate_answer`)를 그대로 쓰되, 화면에서만 다음을 더한다. 평가 CLI(`KnowledgeAgent`)와 `configs/default.yaml` 은 바꾸지 않았다.

- 원질문과 리라이트 질의를 둘 다 검색해 RRF 로 합친다 (짧은 단어·비교 질문의 검색 누락 보완)
- 질문에 적힌 '법령명 제N조(의M)'·사건번호의 원문을 근거 맨 앞에 넣는다 (법령명이 없으면 민법). 예: '민법 제134조' 질문에 민사소송법 제134조가 검색되던 문제
- 리랭커 점수 문턱(`rerank.min_score`)으로 생성을 건너뛰지 않는다 — 답할 수 있는지는 LLM 이 근거를 보고 판단
- 답변 최대 토큰을 4000 으로 늘리고, 생성 오류는 한 번 다시 시도한다
- 모델이 '근거가 일부뿐'이라 표시했지만 인용과 답이 있으면 `status_kind: partial` 로 답을 보여 주고 안내를 붙인다

## 시험지 전체 풀이

`POST /api/chat` 은 한 번에 5문항까지만 푼다. 시험지 전체는 문항을 하나씩 요청한다.

| 경로 | 내용 |
|---|---|
| `POST /api/exam/parse` | `{text}` (시험지 텍스트) 또는 `{exam}` (`kant-rag import-exam` 형식 JSON) → 문항 목록과 `batch_id`. LLM·검색 없이 즉시 |
| `POST /api/exam/solve` | `{batch_id, index, model, mode, preset}` → 그 문항 하나의 풀이. 서버가 다시 켜져 시험지가 없으면 `code: "expired"` (화면이 다시 해석) |

- 화면: 클립(시험지)으로 `.txt`·`.json` 첨부, 또는 문항이 2개 이상인 텍스트를 붙여 넣으면 전체 풀이로 바뀐다.
- 진행률·지금 푸는 문항·남은 시간(푼 문항 평균 시간 기준), 멈추기/이어 풀기, 문항 바로가기 표.
- 채점: JSON 에 정답(`answer`/`accepted`)이 있으면 자동 채점, 없으면 정답을 입력(`2 5 5 …` 또는 `3:2, 5:5`, CSV 붙여넣기). 오답만 보기, 오답 노트에 일괄 담기, CSV 내보내기.
- **정답은 채점에만 쓰고 풀이 입력에서는 지운다** (`answer`·`accepted`·`statement_labels`·`evidence` 제거 후 `MCQSolver.solve`). 테스트로 확인.

## 화면에서 하지 않는 것 (엔진이 제공하지 않음)

- **헷갈리기 쉬운 핵심 법리** 요약 — 엔진 출력에 없어 넣지 않았다. 넣으려면 서버에 요약 LLM 호출 추가가 필요하다.
- **좋아요·싫어요** — 저장할 서버 기능이 없어 표시하지 않는다.
- **진행 단계 표시** — 엔진이 단계 정보를 실시간으로 주지 않아 경과 시간만 보여 준다.
- 대화 기록·오답 노트는 브라우저(localStorage)에만 저장된다.

주소 `#c=<대화 id>&doc=<근거 번호>` 로 대화와 근거를 바로 열 수 있고, `#team` 은 팀 소개를 연다.

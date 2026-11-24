---
stage: FE
tickets: [TKT-FE-M3-01]
status: done
inputs_read: [AR-MAP, AR-HAND, PM-SCR, PM-AC, AR-API, AR-CONV, AR-GATE, BE-BRIEF, CR-LOG]
next_readers: [QA]
---
# 프론트엔드 브리핑 — TKT-FE-M3-01

## [기능] SCR-01 문항 풀이 화면 (Streamlit)
결론: 수용 기준 3개 중 3개 충족 · 상태 6종 표시 · 실제 서비스(시험 DB·OpenAI·GPU 재정렬)로 브라우저 확인

### 사람이 결정할 것
- 없음. (작업 중 결정 1건: 인용 "출처 링크" → 국가법령정보센터 통합검색, 사용자 결정 2026-11-24 — 아래 "기록 필요")

### 이해 가이드
- 데이터 흐름: 제출 버튼 `on_click=_start`가 입력을 `session_state["pending"]`에 잡고 `running=True`(버튼 비활성) → 다음 실행에서 `st.spinner("처리 중…")` 안에서 `runtime.service.answer(item, config)` 동기 호출 → `AnswerEnvelope`를 `session_state["envelope"]`에 두고 `running=False`, `st.rerun()` → `render_result`가 결과 종류별로 그림.
- 자원: `_cached_runtime()`(`st.cache_resource`)가 `entrypoints.composition.build_answer_runtime`으로 DB 연결·검색기·재정렬·생성기를 프로세스당 한 번 만든다. 답변은 캐시하지 않는다(§7).
- 에러: 답변 중 예외는 모두 `AnswerService`가 결과로 바꿔 돌려준다(화면은 판정하지 않음). 화면 쪽 예외는 조립 실패 하나뿐이며 로그를 남기고 "검색 오류"로 표시.
- 먼저 읽을 파일 3곳:
  - `src/lawqa/entrypoints/streamlit_app.py` — 화면 전체(입력 폼, 처리 중 상태, 결과 종류별 표시)
  - `src/lawqa/answering/application/answer_service.py` — 화면이 받는 `AnswerEnvelope`
  - `tests/unit/entrypoints/test_streamlit_app.py` — `AppTest` + 대역 서비스로 상태별 확인

### 수용 기준
| 번호 | 내용 | 충족 | 근거 |
|---|---|---|---|
| AC-11-1 | 제출하면 처리 중 표시 후 결과 종류에 맞는 표시 | 충족 | `test_ac_11_1_answered_shows_number_judgments_citations_and_search_info`, `..._insufficient_...`, `..._input_error_shows_only_warning`, `test_retrieval_error_shows_error_distinct_from_insufficient`, `test_processing_state_disables_submit_button` / 브라우저: 제출 직후 버튼 비활성·"처리 중" → "결과 종류: 성공 — 정답: ①"(screenshots/scr-01-processing-1280.jpg, scr-01-answered-1280.jpg) |
| AC-11-2 | 어떤 상태에서도 "학습용" 안내 한 줄 | 충족 | `test_ac_11_2_notice_visible_before_submit`, `test_ac_11_2_notice_visible_in_every_result_state`(5종) |
| AC-11-3 | 모델 오류는 근거 부족과 다른 문구·표시 | 충족 | `test_ac_11_3_model_error_differs_from_insufficient` — 모델 오류 `st.error` "답변 생성 오류", 근거 부족 `st.info` "정보 부족…" |

상태 6종(07-screens §4): 처리 중(버튼 비활성+spinner) / 성공(`st.success` 정답 번호, 보기별 판단 표, 인용 목록+본문 펼치기, 검색 정보) / 근거 부족(`st.info`, 번호 없음, 인용이 있는 판단은 "보기별 판단 (참고)") / 입력 오류(`st.warning`만, 다른 결과 내용 없음, 입력 유지) / 검색 실패(`st.error` "검색 오류") / 모델 오류(`st.error` "답변 생성 오류").

### 구현 중 자율 결정
#### 결과 종류 표시 문구
- 결정: 결과 줄은 `결과 종류: <07-screens 표의 이름> — <AnswerService의 user_message>`(성공은 `정답: ③`) — 07-screens §2·§4, 04-interfaces-api §4
- 선택지: **A. 화면 이름 + 서비스 문구 (권장·채택)** / B. 서비스 문구만
- 권장 이유: 결과 종류 5종을 글자로 보여야 하고(§3 "5종 중 하나를 글자로"), 문구는 도메인이 정한 것을 그대로 쓴다.
- trade-off: A — 입력 오류는 "입력 오류"가 두 번 보임(`입력 오류 — 입력 오류: 지문이…`). B — 결과 종류 이름이 화면마다 달라질 수 있음.

#### 처리 중 버튼 비활성 방식
- 결정: 제출 `on_click`에서 `running=True` → 다음 실행에서 버튼 `disabled` + spinner 안에서 답변 → `running=False` 후 `st.rerun()`
- 선택지: **A. 상태값 + 다시 그리기 (권장·채택)** / B. 폼 제출만(실행 중 버튼이 눌리는 것을 막지 못함)
- 권장 이유: §7 "버튼 비활성"을 실제로 보장하고 중복 제출을 막는다.
- trade-off: A — 제출마다 화면을 한 번 더 그림. B — 처리 중 다시 눌러 중복 호출 가능.

#### 표는 `st.dataframe`, 본문은 `st.text`
- 결정: 모델이 만든 이유·청크 본문은 마크다운으로 해석하지 않는 요소로만 표시
- 선택지: **A. 표·평문 (권장·채택)** / B. `st.markdown`
- 권장 이유: 판례 본문·모델 출력 안의 기호가 서식·링크로 바뀌지 않는다(보안 체크리스트: 이스케이프 없이 렌더링하지 않음).
- trade-off: A — 굵게 등 서식 없음. B — 모델 출력이 화면 구조를 바꿀 수 있음.

#### 조립 실패 표시
- 결정: DB·모델 조립 자체가 실패하면 로그(`streamlit_runtime_failed`)를 남기고 "결과 종류: 검색 실패 — 검색 오류" — §4 문구
- 선택지: **A. 검색 실패로 표시 (권장·채택)** / B. Streamlit 기본 예외 화면
- 권장 이유: 사용자에게 예외 원문(접속 정보 포함 가능)을 보이지 않는다.
- trade-off: A — 원인은 로그를 봐야 앎. B — 스택·설정 값 노출 가능.

### 알려진 위험
| 위험 | 이번에 한 대응 | 남은 것 |
|---|---|---|
| 첫 제출이 느림(재정렬 모델 적재 약 20초) | `st.cache_resource`로 프로세스당 1회 | 시연 전 한 번 제출해 데우기 |
| 375px에서 판단·인용 표가 넓음 | 표는 `use_container_width`로 화면 폭에 맞추고 칸 안에서 가로 스크롤(페이지 자체는 넘치지 않음) | 이유가 긴 칸은 잘려 보임(표 칸을 누르면 전체 보임) |
| DB 연결을 프로세스 동안 열어 둠 | 읽기만 함, 트랜잭션은 서비스가 열고 닫음 | 서버를 오래 띄우면 DB 재시작 시 다시 띄워야 함 |
| 불완전 색인으로 검색 | CR-008대로 결과 위에 경고 한 줄 | 빈 판례 삭제·재색인은 사람 작업 |

### 검증 결과
- GATE-04: `uv run pytest tests/unit -q` → 286 passed(이번 티켓 15개)
- GATE-05: `uv run ruff check .` 통과 / `uv run ruff format --check .` 151 files already formatted
- GATE-01 일부(화면 기동): `uv run streamlit run src/lawqa/entrypoints/streamlit_app.py`(시험 DB를 `DATABASE_URL`로 지정, 포트 8511) → HTTP 200, 브라우저에서 민법 제2조 문항 제출 → 처리 중 → 성공(정답 ①, 인용 민법 제2조·제1조, 불완전 색인 경고)
- 스크린샷: `docs/05-frontend/screenshots/scr-01-processing-1280.jpg`, `scr-01-answered-1280.jpg`, `scr-01-answered-375.jpg`
- audit: 해당 없음(새 의존성 없음, streamlit은 기존 스택)

### 명세와 다르게 한 것
- 없음. ("출처 링크" 대상은 명세에 없어 사용자에게 확인함)

### 기록 필요
- 인용 "출처 링크" = 원문 위치 글로 만든 국가법령정보센터 통합검색 주소(`https://www.law.go.kr/LSW/totalSearch.do?query=<위치>`), 사용자 결정 2026-11-24. 07-screens §3 "출처 링크" 항목에 대상을 적어 두면 좋다(PM 갱신 요청).

### 변경 범위
- `src/lawqa/entrypoints/streamlit_app.py`(새 파일), `tests/unit/entrypoints/test_streamlit_app.py`(새 파일), `docs/05-frontend/briefing-TKT-FE-M3-01.md`, `docs/05-frontend/screenshots/*`
- 공통 파일·다른 단계 경로 수정 없음. 새 의존성 없음.

### 확인하지 못한 것
- 브라우저에서 근거 부족·입력 오류·검색 실패·모델 오류 상태는 대역 시험(`AppTest`)으로만 확인(실제 화면은 성공 상태만).
- 768px 화면 폭은 찍지 않음(1280·375만).
- 키보드만으로 조작·색 대비는 Streamlit 기본 테마에 맡김(C-16, 스타일 기준 없음).
- UX 문서 미배포 경고(UX-PLAN-FE 등)는 이 프로젝트가 UX 단계를 쓰지 않아(C-16) 해당 없음.

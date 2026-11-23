# ADR-010: reranker
- 상태: Accepted (user, 2026-11-23) — LangChain `ContextualCompressionRetriever` + `CrossEncoderReranker`, 모델 `BAAI/bge-reranker-v2-m3` 로컬 GPU
- 관련 계층: [인프라] [모듈 협력 구조]
- 근거: C-03, C-05, AQ-001, REQ-051, REQ-053, RISK-14, NFR-02, ADR-009, ADR-011

## 맥락 (조사 2026-11-23)
구성 C는 보기마다 B 후보 `N_fuse`개를 다시 평가한다(문항당 질의–청크 쌍 약 100개). 응답 시간 중앙값 30초 이내(NFR-02). 이 PC에 RTX 5060 Laptop 8GB가 있다. 사용자는 발제 구조대로 Retriever + Reranker를 LangChain 표준 부품으로 조합하기로 했다.

## 검토한 옵션
| 옵션 | 장점 | 단점 | AI 부채 영향 | 외부 기준 영향 | 되돌리기 비용 |
|---|---|---|---|---|---|
| A. `bge-reranker-v2-m3` 로컬 cross-encoder(GPU) (선택) | 결정적, 비용 0, 질의–청크 관련도 재평가(REQ-053) | PyTorch(CUDA) 설치, RTX 50 계열 호환 버전 필요 | 낮음 | CRT-05 분명 | 낮음 |
| B. Cohere rerank | 설치 없음 | 무료 한도(분당 10회)로 평가 느림, 키 추가 | 중 | 중립 | 낮음 |
| C. LLM 재정렬(`gpt-6-luna`) | 설치·키 없음 | 비결정적, 생성 효과와 섞임 | 중 | 해석 약함 | 낮음 |

## 결정
A.
- 조립: `ContextualCompressionRetriever(base_compressor=CrossEncoderReranker(model=HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-v2-m3", model_kwargs={"device": reranker_device}), top_n=K_opt), base_retriever=<구성 B EnsembleRetriever>)`.
- 기록: 재정렬 전 순위 = B 결과 순서, 재정렬 후 순위 = C 결과 순서. 재정렬 점수는 `CrossEncoderReranker`가 문서에 붙이지 않을 수 있어(미확인, A6 스택 주의) 같은 `HuggingFaceCrossEncoder.score()`로 후보 점수를 구해 기록한다(AC-08-1·2).
- `reranker_device`는 설정(`cuda` 기본, 실패 시 `cpu`로 바꿔 지연을 기록).

## 결과
- 좋아지는 점: C가 외부 호출 없이 결정적
- 감수할 점: PyTorch CUDA 빌드 설치 크기, 모델 첫 다운로드(약 2.3GB, 저장소 밖 캐시)
- 후속 작업: TKT-BE(재정렬 조립), US-03 시험 실행에서 GPU 동작·지연 확인

## 쉬운 설명
- A. 내 GPU의 재정렬 모델(선택): 무엇이 달라지나 — 노트북 GPU에서 "질문과 근거가 얼마나 맞는지"를 다시 점수 매긴다. / 좋은 점 — 같은 입력이면 같은 결과, 비용 없음. / 감수할 점 — GPU용 PyTorch 설치가 크다. / 나중에 바꾸기: 쉬움.
- B. Cohere 서비스: 무엇이 달라지나 — 외부 서비스에 맡긴다. / 좋은 점 — 설치가 없다. / 감수할 점 — 무료 한도가 작다. / 나중에 바꾸기: 쉬움.
- C. GPT로 재정렬: 무엇이 달라지나 — 답변 모델이 순서도 정한다. / 좋은 점 — 추가 설치 없음. / 감수할 점 — 매번 결과가 다르고 효과 구분이 어렵다. / 나중에 바꾸기: 쉬움.

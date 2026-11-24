# 교안 기준 프로젝트 스택 (RAG 파이프라인 설계 → 프로젝트 3)

원본: 노션 「📕 RAG 파이프라인 설계」 https://app.notion.com/p/4175caf56ec880dd8012d435f35eb0b7
장별 상세: [ch1-2.md](ch1-2.md) · [ch3-4.md](ch3-4.md) · [ch5.md](ch5.md) · [ch6-7.md](ch6-7.md)

원칙: **교안에 있는 방식은 교안대로.** 교안에 없거나 교안끼리 어긋나는 부분만 아래 「프로젝트 결정」으로 정하고, 바꾼 이유를 report.md에 남긴다.

## 1. 교안 표준 (그대로 따름)

| 영역 | 교안 방식 | 출처 |
|---|---|---|
| 환경 | `uv init <name> --python 3.13`, `uv add ...`, Jupyter(ipykernel), 버전은 `uv.lock`으로 고정 | 1·2장 |
| `.env` | `OPENAI_API_KEY`, `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres` | 2-5 |
| 패키지 | langchain, langchain-core, langchain-community, langchain-classic, langchain-openai, langchain-text-splitters, langchain-postgres, `psycopg[binary,pool]`, python-dotenv, rank_bm25, sentence-transformers (+ 평가: ragas, datasets, pandas) | 전 장 |
| LLM | `init_chat_model(...)` 방식은 교안대로. **모델은 팀 통일 `gpt-6-luna`** (교안 표기 gpt-5-mini는 잘못된 것으로 팀 확인), temperature 미지원이라 생략 | 3장 |
| 임베딩 | `OpenAIEmbeddings(model="text-embedding-3-small")` (1,536차원) + `CacheBackedEmbeddings`/`LocalFileStore` | 2-4 |
| 분할 | `RecursiveCharacterTextSplitter`, `split_documents()`로 메타데이터 보존. 규정·매뉴얼류 권장 200~500자 | 1-5, 2-2, 2-3 |
| 벡터 DB | PostgreSQL 17 + pgvector (`pgvector/pgvector:pg17` Docker), `langchain_postgres.PGVector(..., use_jsonb=True)` | 2-5 |
| 증분 색인 | `SQLRecordManager` + `index(cleanup="incremental", source_id_key="source")` | 2-7 |
| 메타데이터 | `source`, `category`, `year`(int), `page`/`section`, `chunk_id` | 1-6, 2-6 |
| 체인 | LCEL: `{context: retriever | format_docs, question: RunnablePassthrough()} | ChatPromptTemplate | model | StrOutputParser()` | 3-6 |
| 프롬프트 | system: "[참고 문서]만 근거로 답, 근거 없으면 '확인할 수 없습니다'" + `{context}` / human: `{question}` (3-6 형태. 3-5는 question 누락 결함) | 3-5, 3-6 |
| 출처 표기 | 검색 문서 메타데이터로 `[참고한 출처]` 출력 | 3-7 |
| 근거 없음 처리 | `similarity_search_with_score` 거리 ≤ 0.60 수동 필터, 0건이면 "찾을 수 없습니다" | 3-3 |
| BM25 | `BM25Retriever.from_documents(docs, preprocess_func=...)` | 5-1 |
| 하이브리드 | `EnsembleRetriever(retrievers=[bm25, vector], weights=[...])` (langchain_classic, 가중 RRF Σw/(rank+60)). 기본 0.5:0.5, 키워드형 0.8:0.2, 의미형 0.2:0.8 | 5-2, 5-3 |
| 리랭킹 | `ContextualCompressionRetriever(base_compressor=CrossEncoderReranker(model=HuggingFaceCrossEncoder("Dongjin-kr/ko-reranker"), top_n=...), base_retriever=...)` | 5-4 |
| 쿼리 변환 | Rewrite / HyDE / Routing / Memory (Multi-Query는 교안에 없음) | 4-4 |
| 평가셋 | 질문 유형 3종: 단순 사실 / 다문서 추론 / 함정(문서에 답 없음). utf-8-sig CSV, 빈 칸 점검, LLM으로 정답-원문 대조 | 7-1, 7-2 |
| 평가 지표 | RAGAS: 검색 = context_precision·context_recall, 생성 = faithfulness·answer(response) relevancy. 판정 LLM `gpt-6-luna`(팀 통일, 교안 표기 gpt-4o-mini) + text-embedding-3-small | 7-3, 7-4 |
| 실패 분석 | 검색 실패(청킹·임베딩·메타데이터 필터) vs 생성 실패(환각·문맥 무시·지시 불이행) | 7-5, 7-6 |
| 회귀 검증 | 같은 평가셋으로 변경 전후 질문별 비교 | 7-7 |

## 2. 프로젝트 결정 (교안에 없거나 어긋나는 부분)

| 항목 | 교안 상태 | 프로젝트 결정(안) | 이유 |
|---|---|---|---|
| Hybrid→Rerank 연결 | 한 코드로 연결한 예 없음 (5-4는 BM25만 rerank) | `base_retriever=EnsembleRetriever`로 교안 구성요소를 조합 | 노션 필수 C 구성 |
| 후보 수 k | 실습은 k=1~3, 이론은 1차 후보 10~20 | 1차 BM25·Vector 각 k=20 → RRF → rerank `top_n=5` | Hit@5를 재려면 최종 5개 필요 |
| 한국어 BM25 토큰화 | 공백 분리만 (조사 붙은 토큰 매칭 실패 사례가 교안 출력에 있음) | 기본은 교안대로 공백 분리. 형태소 분석기(kiwipiepy)는 **비교 실험**으로만 추가 | 법률 문장은 조사·복합어가 많음. 바꾸면 근거 수치 남김 |
| 청킹 | 범용 200~500자 (RecursiveCharacterTextSplitter) | **팀 결정 `field`**: 판시사항·판결요지를 원래 항목([1][2]/가.나.) 단위로 한 조각씩, 글자 수 분할 없음, 판결 전문 제외, 참조조문·참조판례는 메타데이터(`ref_articles`, `ref_cases`). 교안 방식은 `CHUNK_STRATEGY=split`으로 비교 | 판례는 원래 구조가 법리 단위로 나뉘어 있음. 조각 수 약 1/4, 임베딩 비용 약 1/8. 요지 없는 판례(주로 하급심 약 12%)는 제외하고 건수 기록 |
| 메타데이터 필터 | 교안 3-4 (dict 필터) | 참조조문 키(`law:민법:750`)로 필터: `--article "민법 제750조"` (PGVector `$like`, BM25 마스크) | 같은 조문을 다룬 판례만 모아 볼 수 있게 |
| 검색 지표 | Hit@k·MRR 없음, RAGAS context 지표만 | 노션 정의대로 **Hit@5**(허용 근거 청크가 상위 5개에 있으면 1) 직접 계산 + RAGAS는 보조 | 노션 평가표 필수 지표 |
| 평가셋 형식 | CSV, 필드명 강의마다 다름 | 노션 요구대로 `eval/dev.json`(10) · `eval/test.json`(20), 필드: id, type, question, expected_facts, allowed_evidence(청크 ID), source_location | 노션 산출물 규격 |
| 답변 정답 | 교안에 정답 충족 지표 없음 | 시험 정답(선지/OX) 일치 = 정답 충족 1/0, 인용이 실제 검색 결과에 있는지 = 근거 적합 1/0 | 노션 채점 기준 |
| 생성·판정 모델 | gpt-5-mini / gpt-4o-mini 혼재 | 생성·RAGAS 판정 모두 **gpt-6-luna** | 팀 통일 (교안·발제 표기 오류 확인, 2026-11-23) |
| 시험 시점 | 교안에 없음 (규정 문서는 시점 문제가 없음) | 판례는 선고일 2025-12-31까지, 법령은 2026-01-01 시행 버전(eflaw)만 색인 | 시험 이후 판례·개정 법령이 근거로 섞이면 출제 당시 정답과 어긋남 |
| Postgres 계정 | 2-5에서 docker(postgress)·DBeaver(password)·.env(postgres) 불일치 | `.env` 기준 `POSTGRES_PASSWORD=postgres`, `POSTGRES_DB=postgres`로 통일 | 교안 오타 정리 |
| PGVector import | 경로 2가지 혼재 | `from langchain_postgres import PGVector` | 3-6/3-7 기준 |
| 쿼리 리라이트(최적화) | 4-4 Rewrite | 교안 Rewrite 방식 사용, 원질문·변환질의 저장, 실패 시 원질문 fallback | 노션 STEP 5 |
| Agentic RAG | 교안 범위 밖 | 필수 평가와 분리한 추가 실험 | 팀 계획 3단계 |

## 3. 교안 코드에서 그대로 쓰면 안 되는 부분
- 3-5 프롬프트: `("human", "{question}")` 누락 → 3-6 템플릿 사용
- 5-5: `qa_prompt | llm` → `llm` 미정의, `model`로
- 2-4 설치 명령에 `langchain-classic` 누락
- 2-6: `cd chapter02-4` 오타, `user_question` 줄 깨짐
- 4-2/4-3 생성 프롬프트에는 "문서 외 추측 금지"가 없음 → 3장 표준 프롬프트로 통일

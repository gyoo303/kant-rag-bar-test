# 5장: 검색 전략 구현 (교안 요약)

출처: Notion "RAG 파이프라인 설계" 5-1 ~ 5-7 (7개 페이지 모두 정상 조회, 빈 페이지 없음).
표기: "(관찰)"은 교안에 직접 쓰여 있지 않고 교안 코드/출력에서 요약자가 읽어낸 사항.

## 공통 환경 (7개 강의 동일 패턴)

- 프로젝트 생성: `uv init chapter05-N --python 3.13` → `cd chapter05-N`
- Python 3.13. **패키지 버전은 어느 강의에서도 고정하지 않음** (`uv add`로 최신 설치, `uv.lock`으로 잠금).
- 폴더 구조 (강의마다 이름만 다름):
  ```
  chapter05-N/
  ├── .venv/  ├── src/chapter05_N/__init__.py
  ├── .env  ├── .gitignore  ├── .python-version
  ├── pyproject.toml  ├── uv.lock
  └── practice_xxx.ipynb      # Jupyter 노트북에서 실습
  ```
- `.env` 키:
  - `OPENAI_API_KEY=sk-proj-...` (따옴표 없이)
  - `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres` (5-2부터, psycopg3 드라이버)
- LLM: `init_chat_model(model="gpt-5-mini", model_provider="openai", temperature=0)` (`from langchain.chat_models import init_chat_model`)
- 임베딩: `OpenAIEmbeddings(model="text-embedding-3-small")` (`from langchain_openai import OpenAIEmbeddings`)
- QA 패턴: `PromptTemplate.from_template("...[참고 문서]:\n{context}\n\n[질문]:\n{question}\n\n[답변]:")` → `qa_prompt | model` → `.invoke({"context": "\n".join(doc.page_content ...), "question": q})` → `response.content`
- 실습 데이터: `Document(page_content=...)` 3~4개짜리 사내 IT 규정/복지 문서 (실제 파일 로딩·청킹 없음)

---

## 5-1. BM25 키워드 검색 구현

**핵심 개념**
- BM25 = TF(단어 빈도) + IDF(역문서 빈도) + 문서 길이 정규화로 순위를 매기는 대표적 키워드(희소, Sparse) 검색.
- 고유명사·전문 용어가 본문에 "정확히 포함"되었는지 찾는 데 강함.
- 토크나이저: 문장을 토큰 목록으로 분절. "공백 기준 또는 한국어 형태소 단위"로 나눈다고 설명.

**사용 기술**
- 설치: `uv add ipykernel langchain langchain-core langchain-community langchain-openai python-dotenv rank_bm25`
- `from langchain_community.retrievers import BM25Retriever` (내부적으로 `rank_bm25` 사용)
- `from langchain_core.documents import Document`
- **한국어 토큰화: 공백 분리(`text.split()`)만 사용.** kiwi/okt 등 형태소 분석기는 5장 전체에서 사용하지 않음.
- `bm25_retriever.k = 2`

**대표 코드**
```py
def custom_tokenizer(text: str) -> list[str]:
    return text.split()

bm25_retriever = BM25Retriever.from_documents(
    documents=raw_documents, preprocess_func=custom_tokenizer)
bm25_retriever.k = 2
docs = bm25_retriever.invoke("재택 근무 VPN 접속")
```

**주의/권장**
- 토크나이저를 "질의 특성에 맞게 설정"하라는 학습 목표가 있으나, 실제 코드는 공백 분리만 시연.
- (관찰) 공백 분리라 "VPN을"과 "VPN"이 다른 토큰이 됨 → 한국어 조사 때문에 매칭 누락 가능. 교안은 이 문제를 언급하지 않음.

---

## 5-2. Hybrid Search 결합

**핵심 개념**
- Hybrid Search = BM25(고유명사·약어 식별) + 벡터 검색(PostgreSQL + pgvector, 문맥·의도 유사 문서) 결합.
- EnsembleRetriever: 두 검색기의 상위 문서 목록에 가중치를 곱해 단일 순위 점수 계산. 0.5:0.5에서 출발해 데이터 특성에 맞게 조정.
- pgvector 장점: 별도 벡터 DB 없이 RDBMS 안에서 본문·메타데이터·벡터를 일원화 관리.

**사용 기술**
- 설치: `uv add ipykernel langchain langchain-core langchain-community langchain-classic langchain-openai langchain-postgres "psycopg[binary,pool]" python-dotenv rank_bm25`
- `from langchain_postgres import PGVector`
- `from langchain_classic.retrievers import EnsembleRetriever` (주의: `langchain_classic` 경로)
- BM25 k=2, 벡터 `search_kwargs={"k": 2}`, `weights=[0.5, 0.5]`
- PGVector collection_name: `"it_regulations_collection"`, `use_jsonb=True`

**대표 코드**
```py
vectorstore = PGVector.from_documents(
    documents=raw_documents, embedding=embeddings,
    connection=os.getenv("DATABASE_URL"),
    collection_name="it_regulations_collection", use_jsonb=True)
vector_retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

hybrid_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],  # 순서: [BM25, Vector]
    weights=[0.5, 0.5])
docs = hybrid_retriever.invoke("외부 장소에서 회사 시스템 연결 시 VPN 보안 수칙")
```

**주의/관찰**
- (관찰) 각 검색기 k=2인데 결과는 3건 → Ensemble은 두 목록의 합집합(중복 제거)을 반환하므로 최종 개수는 k보다 클 수 있음.
- `사용 프로그램` 목록에는 langchain-classic이 빠져 있지만 설치 명령에는 포함됨.

---

## 5-3. RRF·가중치 튜닝

**핵심 개념**
- RRF(Reciprocal Rank Fusion, 상호/역순위 융합): BM25 점수(0~수십)와 코사인 유사도(0~1)는 직접 비교 불가 → 절대 점수 대신 **순위의 역수**를 합산.
- 공식: `1 / (순위 + k)`, 가중 적용 시 `score = Σ weight_i * 1/(rank_i + c)`
- **상수 k(c) = 60** ("일반적으로 60", 1위·2위 점수 차가 과도하게 벌어지는 것 방지)
- 질의 유형별 가중치 (BM25 : Vector):

| 질의 유형 | 추천 가중치 | 특징 |
|---|---|---|
| 고유명사·약어 중심 | 0.8:0.2 또는 0.7:0.3 | 특정 단어가 본문에 반드시 있어야 할 때 |
| 일반 균형 검색 | 0.5:0.5 | 단어 일치·의미 균등 |
| 의도·서술형 뉘앙스 | 0.2:0.8 또는 0.3:0.7 | 단어 불일치여도 맥락적 동의어 필요 |

**사용 기술**
- 설치: 5-2와 동일.
- BM25 k=3, 벡터 k=3, collection_name `"it_regulations_tuning"`
- `keyword_tuned_retriever` weights=[0.8, 0.2], `semantic_tuned_retriever` weights=[0.2, 0.8]
- EnsembleRetriever의 RRF 상수 인자는 코드에서 명시적으로 설정하지 않음 (기본값 사용).

**대표 코드 (RRF 수동 검증)**
```py
C_CONSTANT = 60
def calculate_rrf_score(rank: int, weight: float, c: int = C_CONSTANT) -> float:
    return weight * (1.0 / (rank + c))
# 문서 A: BM25 1위, Vector 2위 / 문서 B: BM25 3위, Vector 1위, weights [0.8, 0.2]
score_a = calculate_rrf_score(1, 0.8) + calculate_rrf_score(2, 0.2)  # 0.016341
score_b = calculate_rrf_score(3, 0.8) + calculate_rrf_score(1, 0.2)  # 0.015977 → A 우선
```

**주의/관찰**
- 순위는 1부터 시작(1-based)으로 계산.
- (관찰) 키워드 튜닝(0.8:0.2)으로 "사내 VPN 연결 가이드"를 검색했는데 1순위가 "계정 관리" 문서 → 공백 토크나이저에서 "사내"는 일치, "VPN"은 "VPN을"과 불일치했기 때문으로 보임. 교안은 원인을 설명하지 않음.
- 결과가 4건(k=3 두 개의 합집합).

---

## 5-4. Re-ranking 적용

**핵심 개념**
- 2단계(2-Stage) 검색: 1단계 Retrieval(빠른 후보 추출, **10~20건**) → 2단계 Re-ranking(소수 후보만 정밀 재정렬, 1~3위 결정).
- Bi-Encoder(벡터 검색: 질문·문서 따로 임베딩, 빠름, 세부 상호작용 놓침) vs Cross-Encoder(질문·문서를 한 쌍으로 동시 입력, 교차 어텐션, 느리지만 정확).
- 리랭커는 ContextualCompressionRetriever의 "압축기(compressor)" 형태로 기본 검색기에 결합.

**사용 기술**
- 설치: 5-2 + `sentence-transformers`
- `from langchain_community.cross_encoders import HuggingFaceCrossEncoder`
- `from langchain_classic.retrievers.document_compressors import CrossEncoderReranker`
- `from langchain_classic.retrievers import ContextualCompressionRetriever`
- **리랭커 모델: `Dongjin-kr/ko-reranker`** (교안 주석: 한국어·영어 지원 다국어 경량 Cross-Encoder)
- 1차 검색기: **BM25 단독**, k=3 → 리랭커 **top_n=2**
- Cohere / FlashrankRerank / bge-reranker 는 사용하지 않음.

**대표 코드**
```py
base_retriever = BM25Retriever.from_documents(raw_documents, preprocess_func=custom_tokenizer)
base_retriever.k = 3
cross_encoder_model = HuggingFaceCrossEncoder(model_name="Dongjin-kr/ko-reranker")
reranker = CrossEncoderReranker(model=cross_encoder_model, top_n=2)
rerank_retriever = ContextualCompressionRetriever(
    base_compressor=reranker, base_retriever=base_retriever)
docs = rerank_retriever.invoke("사내 망 들어가려다 비밀번호 여러 번 틀렸을 때 처리 방법")
```

**결과/강조점**
- BM25 단독: "비밀번호" 단어 일치로 보안 규정이 1위 → 리랭킹 후 "계정 관리(5회 로그인 실패)"가 1위로 역전.
- 무거운 모델은 후보군(Top-k)에만 적용해야 속도·정확도 모두 확보.
- 실습은 BM25 → rerank이며, Hybrid(Ensemble) → rerank 조합 코드는 5장에 없음.

---

## 5-5. 맥락 압축·검색 최적화

**핵심 개념**
- 맥락 압축(Contextual Compression): 검색된 문서 전체가 아니라 질문 관련 핵심 문장만 발췌해 LLM에 전달.
- 문서 전체 전달의 한계: 토큰 낭비·비용 증가, Lost in the Middle(중간 정보 누락), 환각 유발.
- 2단계: 기본 검색(BM25/벡터) → 압축기(Compressor)가 무관한 문장 삭제/핵심 문장 추출.
- 리랭킹 = 문서 단위 순서 재배열, 맥락 압축 = 문서 내부 문장 잘라내기.

**사용 기술**
- 설치: 5-4와 동일 (sentence-transformers 포함, 본 강의에선 미사용)
- `from langchain_classic.retrievers.document_compressors import LLMChainExtractor`
- `from langchain_classic.retrievers import ContextualCompressionRetriever`
- 압축기 LLM: gpt-5-mini (temperature=0). 기본 검색기 BM25 k=2.
- ContextualCompressionRetriever 필수 인자: `base_compressor`, `base_retriever`

**대표 코드**
```py
compressor = LLMChainExtractor.from_llm(model)
compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor, base_retriever=base_retriever)
docs = compression_retriever.invoke("사내 복지 포인트 남으면 다음 해로 넘겨서 쓸 수 있나요?")
```

**주의/관찰 (교안 코드 오류 포함)**
- 3.4 코드에 `qa_chain = qa_prompt | llm` → `llm`은 정의되지 않음(위에서 `model`로 정의). `model`로 써야 함.
- 주석은 "검색 개수를 1개로"인데 실제 코드는 `base_retriever.k = 2`.
- (관찰) 출력상 압축 후에도 복지 문서 문장은 원문 그대로 남고, 무관한 2번째 문서(근무 환경)가 제거됨 → 실습에서는 "문장 절단"보다 "무관 문서 제거" 효과가 나타남.

---

## 5-6. 질의 유형별 검색 결과 비교

**핵심 개념**
- 3가지 질의 유형: 고유명사·단순 키워드형(Exact Keyword) / 의미 탐색형(Semantic/Intent) / 복합 조건형(Complex Multi-condition).
- BM25 실패 원인: 어휘 불일치(Vocabulary Mismatch). 벡터 실패 원인: 전문 용어 왜곡, 지나치게 포괄적 유사도 매칭(희귀 코드·일련번호를 평균적 의미로 흡수).
- 검색 실패 분석(Retrieval Failure Analysis)을 하이브리드/가중치 튜닝의 근거로 삼음.

**사용 기술**
- 설치: 5-4와 동일 (PostgreSQL 패키지 설치하지만 **실제로는 `InMemoryVectorStore` 사용**)
- `from langchain_core.vectorstores import InMemoryVectorStore`
- BM25 k=1, 벡터 k=1 (top-1 비교). 문서에 `metadata={"category": ..., "doc_id": ...}`
- 진단 LLM: gpt-5-mini

**비교 실험 방식**
- 테스트 세트 3건: `고유명사형 "개더타운 접속 일정"`, `의미 탐색형 "새로 들어온 신입 직원 교육은 어디서 하나요?"`, `복합 조건형 "퇴사할 때 사내 계정 정리는 몇 시에 진행돼?"`
- 각 질의에 대해 BM25 top-1 vs Vector top-1 본문을 나란히 출력하고 `comparison_records` 리스트(dict: type/query/bm25/vector)에 저장.
- **정량 지표(Recall, MRR, nDCG, Hit rate 등)는 사용하지 않음.** 평가는 육안 대조 + LLM 진단 리포트(정성).
- 결과: 고유명사형·복합 조건형은 둘 다 정답, 의미 탐색형은 BM25 실패(보안 규정 반환), Vector 성공.

**대표 코드 (LLM 진단 리포트)**
```py
report_prompt = PromptTemplate.from_template(
    "...[질문 유형]: {query_type}\n[질문]: {query}\n"
    "[BM25 검색 결과]: {bm25_result}\n[벡터 검색 결과]: {vector_result}\n\n"
    "두 검색 결과의 적합성을 평가하고, 특정 검색기가 실패했다면 그 원인(단어 불일치, 어휘 유사도 왜곡 등)을 "
    "2줄 이내의 객관적인 문장으로 분석하여 리포트를 작성하세요.\n\n[진단 리포트]:")
diagnostic_chain = report_prompt | model
diagnostic_chain.invoke({"query_type": c["type"], "query": c["query"],
                         "bm25_result": c["bm25"], "vector_result": c["vector"]})
```

---

## 5-7. 검색 전략 선택·개선

**핵심 개념**
- 질의 유형 → 최적 전략 매핑:

| 질의 유형 | 특징 | 최적 전략 |
|---|---|---|
| 고유명사·단순 키워드형 | 시스템 코드, 약어, 조항 번호 | BM25 |
| 의미 탐색형 | 구어체, 동의어, 상황 묘사 | Vector |
| 복합 조건형 | 여러 조건·맥락 혼합 | Vector (또는 Hybrid) |

- 동적 라우팅(Query Routing): LLM 분류기(Router)가 질문 의도를 먼저 분석해 검색기로 분기.

**사용 기술**
- 설치·데이터·검색기: 5-6과 동일 (BM25 k=1, InMemoryVectorStore k=1)
- `from langchain_core.output_parsers import StrOutputParser`
- 라우터: `router_prompt | model | StrOutputParser()` → 출력 "bm25" 또는 "vector"

**대표 코드**
```py
router_prompt = PromptTemplate.from_template(
    "...정확한 일치가 필요한 단어가 포함된 경우: bm25\n"
    "- 구어체이거나 의미/뉘앙스 기반 서술형인 경우: vector\n\n"
    "[질문]: {query}\n[선택 결과 (bm25 또는 vector만 출력)]:")
router_chain = router_prompt | model | StrOutputParser()

def route_and_retrieve(query: str) -> dict:
    decision = router_chain.invoke({"query": query}).strip().lower()
    docs = bm25_retriever.invoke(query) if "bm25" in decision else vector_retriever.invoke(query)
    ...
```

**비교 실험 방식**
- 5-6과 같은 3개 테스트 케이스를 라우팅 파이프라인에 넣어 "선택된 전략 + top-1 본문"을 출력, 5-6의 단일 검색기 결과와 개선 전후 대조(정성).
- 결과: 고유명사형→BM25, 의미 탐색형→Vector(5-6의 BM25 실패 해소), 복합 조건형→BM25(정답).

**주의/관찰**
- 표는 복합 조건형에 "Vector(또는 Hybrid)"를 권장하지만, 실제 라우터는 2분기(bm25/vector)뿐이고 Hybrid 분기는 구현되지 않음. 출력에서 복합 조건형은 BM25로 라우팅됨.
- 라우팅 결과 파싱은 `"bm25" in decision` 문자열 포함 검사, 그 외는 모두 vector로 폴백.

---

## 5장 공통 스택 요약

**교안이 가르친 Hybrid + Rerank 레시피 (5-2/5-3/5-4를 합친 형태)**

1. 환경: `uv init <proj> --python 3.13` → `uv add ipykernel langchain langchain-core langchain-community langchain-classic langchain-openai langchain-postgres "psycopg[binary,pool]" python-dotenv rank_bm25 sentence-transformers` (버전 미고정)
2. `.env`: `OPENAI_API_KEY`, `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres`
3. BM25: `BM25Retriever.from_documents(docs, preprocess_func=lambda t: t.split())`, `k` 설정 (교안 값 2~3, 이론상 1차 후보 10~20건)
4. Vector: `PGVector.from_documents(docs, OpenAIEmbeddings(model="text-embedding-3-small"), connection=DATABASE_URL, collection_name=..., use_jsonb=True).as_retriever(search_kwargs={"k": ...})`
5. 융합: `EnsembleRetriever(retrievers=[bm25, vector], weights=[...])` (langchain_classic). 내부적으로 가중 RRF `Σ w/(rank+60)`. 기본 0.5:0.5, 키워드형 0.8:0.2(0.7:0.3), 의미형 0.2:0.8(0.3:0.7)
6. 리랭크: `ContextualCompressionRetriever(base_compressor=CrossEncoderReranker(model=HuggingFaceCrossEncoder(model_name="Dongjin-kr/ko-reranker"), top_n=2), base_retriever=<1차 검색기>)`
7. (선택) 맥락 압축: `LLMChainExtractor.from_llm(model)`를 compressor로 쓰는 ContextualCompressionRetriever
8. (선택) 라우팅: LLM 라우터(`prompt | model | StrOutputParser()`)로 질의 유형별 검색기/가중치 선택
9. 생성: `init_chat_model("gpt-5-mini", model_provider="openai", temperature=0)` + `PromptTemplate` `{context}`/`{question}` → `qa_prompt | model`

**강의 간 불일치·공백**
- Hybrid → Rerank를 한 번에 연결한 코드는 5장에 없음. 5-4 리랭크의 base_retriever는 BM25 단독. 위 6단계에서 base_retriever에 EnsembleRetriever를 넣는 것은 교안 구성요소의 조합이지 교안 시연 코드가 아님.
- 벡터 저장소: 5-2/5-3은 PGVector, 5-6/5-7은 InMemoryVectorStore (PG 패키지·DATABASE_URL은 설치/설정만 함). 5-4/5-5는 벡터 검색기 미사용.
- k 값이 강의마다 다름: 5-1/5-2 k=2, 5-3/5-4 k=3, 5-5 k=2(주석은 1), 5-6/5-7 k=1. 5-4 이론은 1차 후보 10~20건이라고 하지만 실습은 3건.
- RRF 상수 60은 5-3 수동 계산 코드에서만 명시. EnsembleRetriever 호출 시 상수 인자를 넘기지 않음.
- 한국어 토큰화는 전 강의 공백 분리. 5-1은 "형태소 단위 분절"을 개념으로만 언급, kiwi/okt 미사용. (관찰) 조사 붙은 토큰("VPN을")이 매칭 실패하는 사례가 5-3 출력에 보임.
- 5-5 코드 `qa_prompt | llm`의 `llm` 미정의(→ `model`).
- 5-7 매핑표는 복합 조건형에 Hybrid를 언급하지만 라우터는 bm25/vector 2분기만 구현.
- 평가: 5-6/5-7 모두 소수 질의(3건)의 top-1 육안 비교 + LLM 진단 리포트. 정량 지표 없음.
- 5-2 `사용 프로그램` 목록에 langchain-classic 누락(설치 명령엔 포함). 5-5~5-7은 sentence-transformers를 설치하지만 사용하지 않음.

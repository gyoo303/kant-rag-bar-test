# ADR-009: 검색기 구성 (BM25 + 벡터 → EnsembleRetriever)
- 상태: Accepted (user, 2026-11-23) — 발제 구조를 따른 LangChain 표준 조합
- 관련 계층: [인프라] [레이어]
- 근거: C-01, C-03, C-05, AQ-001, AQ-003, ADR-006, REQ-049, REQ-050, REQ-052

## 맥락 (조사 2026-11-23)
벡터는 PostgreSQL pgvector에 둔다(ADR-006). 사용자는 "발제 문서대로 Retriever + Reranker 구조"를 LangChain 표준 부품 조합으로 하기로 했다(2026-11-23 답).

## 검토한 옵션
| 옵션 | 장점 | 단점 | AI 부채 영향 | 외부 기준 영향 | 되돌리기 비용 |
|---|---|---|---|---|---|
| A. LangChain 표준 조합: `BM25Retriever`(Kiwi) + `PGVector`(langchain-postgres) → `EnsembleRetriever` (사용자 선택) | 직접 작성 코드 최소, 수업 내용과 같음 | 벡터가 LangChain 관리 표(`langchain_pg_collection`, `langchain_pg_embedding`)에 따로 저장 → 청크 ID를 문서 ID로 맞춰 연결 | 낮음 | CRT-04 | 낮음 |
| B. 벡터 검색기만 우리 청크 표를 감싼 클래스로 작성 | 표 하나로 관리 | 코드 증가 | 낮음 | CRT-04 | 낮음 |

## 결정
A.
- **구성 A(Vector)**: `PGVector(collection_name=f"chunks_{index_version}", embeddings=OpenAIEmbeddings(model="text-embedding-3-small"), connection=DATABASE_URL, use_jsonb=True)`의 `as_retriever(search_kwargs={"k": N_vec})`. 문서 ID(`ids`)는 우리 `chunk_id`.
- **구성 B(Hybrid)**: `BM25Retriever.from_documents(chunks, preprocess_func=kiwi_tokenize, k=N_bm25)`와 A를 `EnsembleRetriever(retrievers=[bm25, vector], weights=[0.5, 0.5], c=60, id_key="chunk_id")`로 결합. `EnsembleRetriever`는 가중 RRF이며 `id_key`로 중복 제거한다 → "RRF로 결합, 같은 가중치, 같은 청크 ID는 한 번"을 기록(REQ-050·052, 단순 점수 합산 아님).
- 결합 전 각 검색기 결과(BM25 목록·벡터 목록과 점수)는 기록용으로 따로 호출해 남긴다(AC-07-1).
- BM25 토큰화: `kiwipiepy` 내용 형태소(명사·동사·형용사 어근·외국어·숫자). BM25 색인은 기동 시 DB 청크로 메모리에 만든다.
- 값 `N_vec`, `N_bm25`, 가중치, `c`는 `config/base.toml [retrieval]`(ADR-011 초기값).

## 결과
- 좋아지는 점: 표준 부품이라 구현·설명 쉬움
- 감수할 점: 청크 본문이 우리 `chunks` 표와 LangChain 임베딩 표에 두 번 저장됨(청크 ID로 일치 검사, A7 게이트)
- 후속 작업: A3 표, TKT-DB(PGVector 적재), TKT-BE(검색기 조립)

## 쉬운 설명
- A. LangChain 표준 부품 조합(선택): 무엇이 달라지나 — 단어 검색기와 벡터 검색기를 LangChain의 "합치기 검색기"로 묶는다. / 좋은 점 — 수업에서 쓰는 부품이라 만들 코드가 적다. / 감수할 점 — 벡터용 표를 LangChain이 따로 만든다. / 나중에 바꾸기: 쉬움.
- B. 벡터 검색기 직접 작성: 무엇이 달라지나 — 우리 표를 직접 검색하는 클래스를 쓴다. / 좋은 점 — 표가 하나다. / 감수할 점 — 코드가 늘어난다. / 나중에 바꾸기: 쉬움.

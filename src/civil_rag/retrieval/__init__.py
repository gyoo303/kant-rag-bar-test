"""검색 (교안 3·4·5장).

구성 (노션 STEP 3, 같은 청크 집합 사용):
- A: Vector baseline — PGVector retriever
- B: Hybrid — BM25Retriever + Vector → EnsembleRetriever(가중 RRF)
- C: Hybrid + re-ranking — ContextualCompressionRetriever(CrossEncoderReranker(ko-reranker))
- (최적화) 쿼리 리라이트 — 원질문·변환 질의 모두 기록, 실패 시 원질문 fallback

모든 검색 결과에 후보 순위·점수, 재정렬 전후 순위를 남긴다.
"""

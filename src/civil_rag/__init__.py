"""민사법 판례·조문 기반 Knowledge Agent.

파이프라인 (노션 STEP 3~5, 교안 기준은 docs/course/STACK.md):
    ingest      판례/조문 원문 → 정제 → 청크(청크 ID·문서 ID·원문 위치) → PGVector 색인
    retrieval   A: Vector / B: BM25+Vector(RRF) / C: B+re-ranking (+ 쿼리 리라이트)
    generation  근거 문맥 주입 프롬프트 → 답변 + 출처, 근거 부족 시 정보 부족 안내
    evaluation  고정 평가셋으로 Hit@5·정답 충족·근거 적합·근거 없음 대응·응답 시간 측정
"""

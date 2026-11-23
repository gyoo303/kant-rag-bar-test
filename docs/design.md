# 설계 · 설정

설정의 단일 출처는 `configs/default.yaml` 이며, 실행 기록마다 `versions` 와 `settings_fingerprint` 가 남습니다.

## 파이프라인
```
질문 ─(선택: 리라이트)─▶ 검색 ─▶ 결합 ─▶ 재정렬 ─▶ 근거 선택 ─▶ 답변·출처 / 근거 부족 안내
                         │
       A: Vector top-k ──┤
       B: BM25 + Vector ─┴─ RRF (score = Σ 1/(rrf_k + rank), chunk_id 기준 중복 제거)
       C: B 후보 fused_k 개 ─ cross-encoder reranker ─ final_k
```

| 단계 | 구현 | 설정 |
| --- | --- | --- |
| 청킹 | `ingest/chunker.py` — 마크다운 절 단위 → 행 묶음, 원문 행·문자 위치 보존 | `chunking.*` |
| BM25 | `retrieval/bm25.py` (rank_bm25, 토크나이저 simple/kiwi) | `retrieval.bm25_k`, `bm25_tokenizer` |
| Vector | `retrieval/vector.py` (FAISS, 정규화 임베딩 내적=코사인) | `EMBEDDING_MODEL`, `retrieval.vector_k` |
| 결합 | `retrieval/hybrid.py` RRF — 점수 척도가 달라 단순 합산하지 않음 | `retrieval.rrf_k`, `fused_k` |
| 재정렬 | `retrieval/rerank.py` cross-encoder (sigmoid 관련도, 사실성 확률 아님) | `RERANKER_MODEL`, `retrieval.final_k` |
| 근거 부족 | C 에서 reranker 최고점 < `rerank.min_score` 면 생성 생략 + LLM `answerable=false` | 개발셋으로만 결정 |
| 답변 | `generation/answer.py` — 인용 ID 가 실제 컨텍스트에 있는지 검증 | `generation.*` |
| 캐시 | `optimize/cache.py` 정확 일치, 키에 버전·모델·설정·사용자 범위 포함, TTL | `optimization.cache` |
| 리라이트 | `optimize/rewrite.py` 질문만 입력, 실패 시 원질문 fallback | `optimization.rewrite` |

## 상태 구분
`ok` / `insufficient_evidence`(정상적 근거 없음) / `retrieval_error` / `generation_error` / `invalid_citation`
— 호출 오류를 '올바른 거절'로 세지 않습니다.

## 보안 · 데이터
- 문서 속 지시문은 신뢰하지 않는 데이터로 취급 (프롬프트에서 `<context>` 로 격리).
- 임베딩·reranker 는 로컬 모델 → 문서는 생성 모델 호출 시에만 외부로 전송. 문서 목록의 `license` 열에 외부 전송 가능 여부 기록.
- `.env`·API 키·개인정보는 커밋하지 않음.

"""문서 처리·색인 (교안 1·2장).

할 일:
- 판례 JSON(law_collector/data/prec) 로딩, <br/> 등 HTML 태그 제거
- 필드 단위 청크: 판시사항 · 판결요지 · 참조조문 · 참조판례 · 판례내용(길면 Recursive 분할)
- 청크 메타데이터: chunk_id, doc_id(판례일련번호), 사건번호, 선고일자, 법원명, section(필드명),
  fetched_at(수집 시점), source="법제처 국가법령정보센터"
- PGVector(use_jsonb=True) 색인 + SQLRecordManager 증분 갱신
- 문서 목록(docs/data_sources.md)과 청크 수·설정 기록
"""

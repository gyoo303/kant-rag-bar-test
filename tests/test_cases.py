import json

from kant_rag.ingest.cases import build_topics, chunk_cases
from kant_rag.schemas import DocumentMeta

META = DocumentMeta(doc_id="CASES", title="판례", source="t", license="t", version="v", path="x", doc_type="cases")


def test_chunk_cases_items_and_date_cut(tmp_path):
    p = tmp_path / "cases.jsonl"
    rows = [
        {"prec_id": "1", "case_no": "2019다12345", "case_name": "x", "court": "대법원", "decided": "2020.01.09",
         "holding_issue": "[1] 쟁점 일 [2] 쟁점 이", "summary": "[1] 요지 일 <br/>내용 [2] 요지 이",
         "ref_articles": "민법 제126조", "ref_cases": "", "topic": "표현대리"},
        {"prec_id": "2", "case_no": "2026다1", "case_name": "y", "court": "대법원", "decided": "2026.02.01",
         "holding_issue": "", "summary": "시험일 이후", "ref_articles": "", "ref_cases": "", "topic": "t"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    chunks = chunk_cases(p, META, date_to="20251231")
    assert [c.chunk_id for c in chunks] == ["CASE#2019다12345#1", "CASE#2019다12345#2"]
    assert "판시사항: 쟁점 이" in chunks[1].text and "민법 제126조" in chunks[1].text


def test_build_topics_from_statute_structure():
    meta = DocumentMeta(doc_id="LAW", title="민법", source="t", license="t", version="v", path="x", doc_type="statute")
    text = "제1편 총칙\n제5장 법률행위\n제3절 대리\n제114조(대리행위의 효력) 내용\n제115조(목적) 내용"
    topics = build_topics([(meta, text)], level="article")
    assert topics[:3] == ["총칙", "법률행위", "대리"] and "대리행위의 효력" in topics and "목적" not in topics
    assert "대리행위의 효력" not in build_topics([(meta, text)], level="section")

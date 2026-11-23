from civil_rag import config
from civil_rag.ingest.chunking import clean_text, law_to_chunks, prec_to_chunks

PREC = {
    "판례정보일련번호": "625343",
    "사건번호": "2025다212572",
    "사건명": "손해배상(기)",
    "법원명": "대법원",
    "선고일자": "20260903",
    "판시사항": "<br/> [1] 법관의 재판상 직무행위로 인한 국가배상책임 요건",
    "판결요지": "[1] " + "가" * 1200,
    "참조조문": "[1] 국가배상법 제2조 제1항",
    "참조판례": "",
    "판례내용": "【원고, 피상고인】 원고<br/>【피고, 상고인】 대한민국",
}


def test_clean_text_removes_tags_and_entities():
    assert clean_text("a<br/>b &amp; <b>c</b>") == "a\nb & c"
    assert clean_text(None) == ""


def test_prec_chunks_ids_sections_and_header():
    chunks = prec_to_chunks(PREC, fetched_at="2026-11-23T10:00:00")
    ids = [c.chunk_id for c in chunks]
    assert ids[0] == "625343:판시사항:0"
    assert "625343:참조판례:0" not in ids                 # 빈 필드는 건너뜀
    long_parts = [c for c in chunks if c.section == "판결요지"]
    assert len(long_parts) >= 3                           # CHUNK_SIZE 초과분 분할
    assert all(len(c.text.split("\n", 1)[1]) <= config.CHUNK_SIZE for c in long_parts)
    first = chunks[0]
    assert first.text.startswith("[2025다212572 손해배상(기) | 판시사항]")
    assert "<br" not in first.text
    assert first.metadata["decision_date"] == "2026.09.03"
    assert first.metadata["fetched_at"] == "2026-11-23T10:00:00"


def test_prec_chunk_ids_are_stable():
    a = [c.chunk_id for c in prec_to_chunks(PREC)]
    b = [c.chunk_id for c in prec_to_chunks(PREC)]
    assert a == b


def test_law_chunks_flatten_paragraphs_and_skip_headings():
    law = {"법령": {
        "기본정보": {"법령명_한글": "민법", "시행일자": "20260317"},
        "조문": {"조문단위": [
            {"조문번호": "1", "조문여부": "전문", "조문내용": "제1편 총칙"},
            {"조문번호": "2", "조문여부": "조문", "조문내용": "제2조(신의성실)", "조문제목": "신의성실",
             "항": [{"항번호": "①", "항내용": "①권리의 행사와 의무의 이행은 신의에 좇아 성실히 하여야 한다."},
                   {"항번호": "②", "항내용": "②권리는 남용하지 못한다."}]},
            {"조문번호": "750", "조문가지번호": "2", "조문여부": "조문", "조문내용": "제750조의2(가상)"},
        ]},
    }}
    chunks = law_to_chunks(law)
    assert [c.chunk_id for c in chunks] == ["law:민법:2", "law:민법:750-2"]
    assert "권리는 남용하지 못한다" in chunks[0].text
    assert chunks[0].metadata["article"] == "제2조"
    assert chunks[1].section == "제750조의2"

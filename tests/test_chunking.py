from civil_rag import config
from civil_rag.ingest.build import decision_date, in_date_range
from civil_rag.ingest.chunking import (
    clean_text,
    law_to_chunks,
    parse_ref_articles,
    parse_ref_cases,
    prec_to_chunks,
    split_items,
)


def test_parse_ref_articles_carries_law_name():
    assert parse_ref_articles("민법 제750조, 제751조 / 민사소송법 제208조") == [
        "law:민법:750", "law:민법:751", "law:민사소송법:208"]
    assert parse_ref_articles("가.나.민사소송법 제204조, 민법 제213조 / 나. 제226조[소의제기]") == [
        "law:민사소송법:204", "law:민법:213", "law:민법:226"]
    assert parse_ref_articles("구 민법(1990. 1. 13. 법률 제4199호로 개정되기 전의 것) 제1008조의3") == ["law:민법:1008-3"]
    assert parse_ref_articles("") == []


def test_parse_ref_cases():
    assert parse_ref_cases("대법원 2003. 7. 11. 선고 99다24218 판결, 대법원 2023. 6. 1. 선고 2021다2022 판결") == [
        "99다24218", "2021다2022"]


def test_split_items_numbered_and_hangul():
    assert split_items("[1] 첫째 법리 [2] 둘째 법리") == [("[1]", "첫째 법리"), ("[2]", "둘째 법리")]
    assert split_items("가. 첫째 법리 나. 둘째 법리") == [("가.", "첫째 법리"), ("나.", "둘째 법리")]
    assert split_items("항목 표시 없는 요지") == [("", "항목 표시 없는 요지")]
    assert split_items("[1] 하나뿐") == [("", "[1] 하나뿐")]          # 항목이 1개면 나누지 않음
    assert split_items("") == []


def test_field_strategy_items_meta_and_no_fulltext():
    prec = {**PREC, "판결요지": "[1] 첫째 요지 [2] 둘째 요지", "참조조문": "[1] 국가배상법 제2조 / [2] 민법 제750조",
            "참조판례": "대법원 2003. 7. 11. 선고 99다24218 판결"}
    chunks = prec_to_chunks(prec, strategy="field")
    ids = [c.chunk_id for c in chunks]
    assert ids == ["625343:판시사항:0", "625343:판결요지:0", "625343:판결요지:1"]   # 전문·참조조문은 조각 아님
    second = chunks[2]
    assert second.text.startswith("[2025다212572 손해배상(기) | 판결요지 [2]]\n둘째 요지")
    assert "참조조문: 국가배상법 제2조, 민법 제750조" in second.text
    assert second.metadata["ref_articles"] == ["law:국가배상법:2", "law:민법:750"]
    assert second.metadata["ref_articles_str"] == "|law:국가배상법:2|law:민법:750|"
    assert second.metadata["ref_cases"] == ["99다24218"]
    assert second.metadata["item"] == "[2]"


def test_law_addendum_articles_after_last_main_article():
    law = {"법령": {
        "기본정보": {"법령명_한글": "어음법", "시행일자": "20100331"},
        "조문": {"조문단위": [{"조문번호": "78", "조문여부": "조문", "조문내용": "제78조(발행인의 책임)"}]},
        "부칙": {"부칙단위": [{"부칙내용": [["제1조 (시행일) 이 법은 공포한 날부터 시행한다.",
                                          "제80조 (소송고지로 인한 시효중단) ①배서인의 …",
                                          "②전항의 규정에 의하여 중단된 시효는 …"]]}]},
    }}
    ids = [c.chunk_id for c in law_to_chunks(law)]
    assert ids == ["law:어음법:78", "law:어음법:80"]          # 부칙 제1조(시행일)는 본문 번호 이하라 제외
    c80 = law_to_chunks(law)[1]
    assert "②전항" in c80.text and c80.metadata["in_addendum"]


def test_field_strategy_skips_case_without_summary():
    prec = {**PREC, "판시사항": "", "판결요지": ""}
    assert prec_to_chunks(prec, strategy="field") == []


def test_exam_date_filter():
    assert decision_date({"선고일자": "2025.12.31"}) == "20251231"
    assert in_date_range({"선고일자": "20251231"}, "", "20251231")
    assert not in_date_range({"선고일자": "20260105"}, "", "20251231")   # 시험 이후 판례 제외
    assert not in_date_range({"선고일자": "20100101"}, "20110101", "")
    assert not in_date_range({"선고일자": ""}, "", "20251231")           # 날짜 모르면 필터 켜졌을 때 제외
    assert in_date_range({"선고일자": ""}, "", "")                       # 필터 끄면 통과

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
    chunks = prec_to_chunks(PREC, fetched_at="2026-11-23T10:00:00", strategy="split")
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
    a = [c.chunk_id for c in prec_to_chunks(PREC, strategy="split")]
    b = [c.chunk_id for c in prec_to_chunks(PREC, strategy="split")]
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

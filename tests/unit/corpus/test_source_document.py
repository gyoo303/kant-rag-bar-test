"""TKT-BE-M2-01: 원문 변환 — 판례 PrecService·민법 텍스트 (ADR-015, AC-05-4 도메인 부분)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lawqa.corpus.domain.errors import (
    DUPLICATE_ARTICLE,
    EMPTY_CONTENT,
    OUT_OF_SCOPE,
    InvalidSourceDocumentError,
    OutOfScopeError,
)
from lawqa.corpus.domain.models import DocumentKind, IndexVersion, SourceDocument, SourceLocation

CIVIL_ACT = Path(__file__).resolve().parents[3] / "law_collector" / "data" / "law" / "민법.txt"


def _prec(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "판례정보일련번호": "112855",
        "사건명": "해고무효확인",
        "사건번호": "94다43351",
        "선고일자": "19951205",
        "법원명": "대법원",
        "사건종류명": "민사",
        "사건종류코드": "400101",
        "판시사항": "  [1] 첫째 판시 <br/>  [2] [1]항의 처분이 정당한 경우<br/>",
        "판결요지": "  [1] 첫째 요지.<br/>  [2] 둘째 요지.<br/>",
        "참조조문": "[1]근로기준법 제27조 제1항<br/>",
        "참조판례": "",
        "판례내용": "【주문】 ... 저장하지 않음",
    }
    data.update(changes)
    return data


def test_from_prec_service_maps_fields_and_cleans_html() -> None:
    doc = SourceDocument.from_prec_service(_prec(), "prec/112855.json")

    assert doc.doc_id == "prec:112855"
    assert doc.kind is DocumentKind.PRECEDENT
    assert doc.title == "해고무효확인"
    assert (doc.case_number, doc.court, doc.case_type) == ("94다43351", "대법원", "민사")
    assert doc.decided_on == date(1995, 12, 5)
    assert doc.holdings == "[1] 첫째 판시\n  [2] [1]항의 처분이 정당한 경우"
    assert "<br/>" not in (doc.summary or "")
    assert doc.referenced_articles == "[1]근로기준법 제27조 제1항"
    assert (doc.source_file, doc.source_line) == ("prec/112855.json", 1)
    assert doc.body is None and len(doc.content_sha) == 64


def test_from_prec_service_keeps_lower_court_precedents() -> None:
    """ADR-015 개정: 데이터출처 대법원 전부(하급심 포함), 법원명으로 거르지 않음."""
    doc = SourceDocument.from_prec_service(_prec(법원명="서울고법"), "prec/1.json")

    assert doc.court == "서울고법"
    assert doc.location.text == "서울고법 1995. 12. 5. 선고 94다43351 판결"


def test_from_prec_service_non_civil_is_out_of_scope() -> None:
    with pytest.raises(OutOfScopeError) as exc_info:
        SourceDocument.from_prec_service(_prec(사건종류명="형사"), "prec/1.json")

    assert exc_info.value.reason == OUT_OF_SCOPE


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"판례정보일련번호": ""}, "MISSING_FIELD:판례정보일련번호"),
        ({"사건번호": None}, "MISSING_FIELD:사건번호"),
        ({"선고일자": "1995.12"}, "BAD_DATE:선고일자"),
        ({"선고일자": "19951345"}, "BAD_DATE:선고일자"),
        ({"판시사항": "<br/>", "판결요지": "  "}, EMPTY_CONTENT),
    ],
)
def test_from_prec_service_invalid_records_have_issue_reason(changes, reason: str) -> None:
    with pytest.raises(InvalidSourceDocumentError) as exc_info:
        SourceDocument.from_prec_service(_prec(**changes), "prec/1.json")

    assert exc_info.value.reason == reason


@pytest.mark.parametrize("value", ["19951205", "1995.12.05", "1995-12-05"])
def test_from_prec_service_accepts_three_date_formats(value: str) -> None:
    doc = SourceDocument.from_prec_service(_prec(선고일자=value), "prec/1.json")

    assert doc.decided_on == date(1995, 12, 5)


def test_from_prec_service_title_falls_back_to_case_number() -> None:
    assert SourceDocument.from_prec_service(_prec(사건명=""), "prec/1.json").title == "94다43351"


STATUTE_SAMPLE = """제1편 총칙
제1장 통칙
제1조(법원) 민사에 관하여 법률에 규정이 없으면 관습법에 의하고 관습법이 없으면 조리에 의한다.
제2조(신의성실)
①권리의 행사와 의무의 이행은 신의에 좇아 성실히 하여야 한다.
② 권리는 남용하지 못한다. <개정 1990.1.13>
제14조의2(특정후견의 심판)
① 가정법원은 특정후견의 심판을 한다.
제50조[분사무소(分事務所) 설치의 등기]법인이 분사무소를 설치한 경우에는 등기하여야 한다.
제3절의2 여행계약 <신설 2015.2.3>
제436조 삭제 <2015.2.3>
제1112조(유류분의 권리자와 유류분) 상속인의 유류분은 다음 각 호에 의한다. <개정 2024.9.20>
1. 피상속인의 직계비속은 그 법정상속분의 2분의 1
1의2. 가상의 호
4. 삭제<2024.9.20>
제3관 파양(罷養) <개정 2012.2.10>
제1항 협의상 파양 <개정 2012.2.10>
제898조(협의상 파양) 양부모와 양자는 협의하여 파양할 수 있다.
"""


def _statutes(text: str = STATUTE_SAMPLE):
    return SourceDocument.statute_articles_from_text(text, "law/민법.txt")


def test_statute_parser_applies_adr015_rules() -> None:
    docs, report = _statutes()

    ids = [d.doc_id for d in docs]
    assert ids == [
        "law:민법:1-0",
        "law:민법:2-0",
        "law:민법:14-2",
        "law:민법:50-0",
        "law:민법:1112-0",
        "law:민법:898-0",
    ]
    assert (report.deleted, report.headings, report.dropped_lines) == (1, 5, 0)
    assert report.issues == ()


def test_statute_parser_titles_bodies_and_lines() -> None:
    docs = {d.doc_id: d for d in _statutes()[0]}

    assert docs["law:민법:1-0"].title == "민법 제1조(법원)"
    assert docs["law:민법:1-0"].source_line == 3
    assert docs["law:민법:2-0"].body == (
        "①권리의 행사와 의무의 이행은 신의에 좇아 성실히 하여야 한다.\n② 권리는 남용하지 못한다."
    )
    assert docs["law:민법:14-2"].title == "민법 제14조의2(특정후견의 심판)"
    assert docs["law:민법:50-0"].article_title == "분사무소(分事務所) 설치의 등기"
    assert docs["law:민법:50-0"].body.startswith("법인이 분사무소를")
    assert docs["law:민법:1112-0"].body == (
        "상속인의 유류분은 다음 각 호에 의한다.\n"
        "1. 피상속인의 직계비속은 그 법정상속분의 2분의 1\n1의2. 가상의 호"
    )
    assert all("<개정" not in d.body and "<신설" not in d.body for d in docs.values())


def test_statute_parser_duplicate_article_is_issue() -> None:
    text = "제1조(법원) 첫 본문\n제1조(법원) 두 번째 본문\n"

    docs, report = _statutes(text)

    assert len(docs) == 1
    assert [(i.source_line, i.reason) for i in report.issues] == [(2, DUPLICATE_ARTICLE)]


def test_statute_parser_drops_lines_before_first_article() -> None:
    docs, report = _statutes("머리말 줄\n제1조(법원) 본문\n")

    assert len(docs) == 1 and report.dropped_lines == 1


def test_ac_full_civil_act_file_parses_1116_articles() -> None:
    """수용 확인(HANDOFF TKT-BE-M2-01): 커밋된 민법.txt 전체 → 조문 1,116·삭제 77·중복 0."""
    docs, report = SourceDocument.statute_articles_from_text(
        CIVIL_ACT.read_text(encoding="utf-8-sig"), "law/민법.txt"
    )

    assert len(docs) == 1116 and report.articles == 1116
    assert report.deleted == 77
    assert report.issues == ()
    assert report.dropped_lines == 0
    assert len({d.doc_id for d in docs}) == 1116
    assert docs[0].doc_id == "law:민법:1-0" and docs[-1].doc_id == "law:민법:1118-0"
    article_50 = next(d for d in docs if d.doc_id == "law:민법:50-0")
    assert article_50.article_title == "분사무소(分事務所) 설치의 등기"


def test_source_location_formats() -> None:
    assert SourceLocation.for_article(245, 0, None).text == "민법 제245조"
    assert SourceLocation.for_article(14, 2, None).text == "민법 제14조의2"
    assert SourceLocation.for_article(103, 0, "제3항~제5항").text == "민법 제103조 제3항~제5항"
    assert (
        SourceLocation.for_precedent(date(2019, 1, 31), "2016다215127", 1).text
        == "대법원 2019. 1. 31. 선고 2016다215127 판결 [1]"
    )


def test_index_version_id_changes_with_settings() -> None:
    class Policy:
        def __init__(self, max_chars: int) -> None:
            self.max_chars, self.overlap_chars = max_chars, 150

    base = IndexVersion.compute_id("abcdef1234", Policy(1500), "text-embedding-3-small", 1536)
    other = IndexVersion.compute_id("abcdef1234", Policy(1200), "text-embedding-3-small", 1536)

    assert base.startswith("idx-abcdef12-") and len(base) == len("idx-abcdef12-") + 8
    assert base != other

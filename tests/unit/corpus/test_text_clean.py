"""TKT-BE-M2-01: 텍스트 정제 (ADR-015)."""

from __future__ import annotations

import pytest

from lawqa.corpus.domain.text_clean import clean_text


@pytest.mark.parametrize("value", [None, "", "   ", "<br/>"])
def test_clean_text_empty_values_become_empty_string(value: str | None) -> None:
    assert clean_text(value) == ""


def test_clean_text_br_becomes_newline_and_trailing_spaces_removed() -> None:
    raw = "  [1] 첫째 항목 <br/>  [2] 둘째 항목<br/>"

    assert clean_text(raw) == "[1] 첫째 항목\n  [2] 둘째 항목"


def test_clean_text_removes_other_tags_and_unescapes_entities() -> None:
    raw = "<p>甲&amp;乙의 <b>계약</b>&nbsp;해제</p><BR>끝"

    # </p> 와 <BR> 은 각각 줄바꿈이라 빈 줄 하나가 남는다
    assert clean_text(raw) == "甲&乙의 계약 해제\n\n끝"


def test_clean_text_collapses_blank_line_runs() -> None:
    assert clean_text("가<br/><br/><br/><br/>나") == "가\n\n나"


def test_clean_text_normalizes_crlf() -> None:
    assert clean_text("가\r\n나\r다") == "가\n나\n다"

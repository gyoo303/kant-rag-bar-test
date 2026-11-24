"""TKT-BE-M2-03: 입력 문항 검증 (R-3, AC-09-4 도메인 부분)."""

from __future__ import annotations

import pytest

from lawqa.retrieval.domain.errors import InvalidExamItemError
from lawqa.retrieval.domain.models import ExamItem

OPTIONS = ("보기1", "보기2", "보기3", "보기4", "보기5")


def test_valid_item_keeps_options_as_tuple():
    item = ExamItem(stem="다음 중 옳은 것은?", options=list(OPTIONS))  # type: ignore[arg-type]
    assert item.options == OPTIONS


@pytest.mark.parametrize("stem", ["", "   \n"])
def test_empty_stem_is_input_error(stem):
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem=stem, options=OPTIONS)
    assert exc.value.field == "stem"


def test_stem_over_4000_chars_is_input_error():
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem="가" * 4001, options=OPTIONS)
    assert exc.value.field == "stem"
    ExamItem(stem="가" * 4000, options=OPTIONS)  # 경계값은 허용


@pytest.mark.parametrize("count", [0, 4, 6])
def test_option_count_must_be_five(count):
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem="지문", options=tuple(f"보기{i}" for i in range(count)))
    assert exc.value.field == "options"
    assert f"현재 {count}개" in exc.value.reason


def test_blank_option_names_its_position():
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem="지문", options=("a", "b", " ", "d", "e"))
    assert exc.value.field == "options[3]"


def test_option_over_1000_chars_is_input_error():
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem="지문", options=("a", "b", "c", "d", "가" * 1001))
    assert exc.value.field == "options[5]"


def test_options_as_string_is_input_error():
    with pytest.raises(InvalidExamItemError) as exc:
        ExamItem(stem="지문", options="abcde")  # type: ignore[arg-type]
    assert exc.value.field == "options"

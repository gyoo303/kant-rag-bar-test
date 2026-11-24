"""TKT-BE-M2-03: 보기별 질의 분해 (ADR-011) · OptionQuery (INV-10)."""

from __future__ import annotations

import pytest

from lawqa.retrieval.domain.decomposer import STEM_PREFIX_CHARS, QueryDecomposer
from lawqa.retrieval.domain.models import ExamItem, OptionQuery


def test_decompose_makes_five_queries_stem_prefix_plus_option():
    item = ExamItem(
        stem="  甲과 乙의 매매계약에 관한 설명 중 옳은 것은?  ", options=tuple("가나다라마")
    )
    queries = QueryDecomposer().decompose(item)

    assert [q.option_no for q in queries] == [1, 2, 3, 4, 5]
    assert queries[0].original == "甲과 乙의 매매계약에 관한 설명 중 옳은 것은?\n가"
    assert all(q.rewritten is None and not q.fallback for q in queries)
    assert all(q.effective == q.original for q in queries)


def test_long_stem_is_cut_to_300_chars():
    item = ExamItem(stem="가" * 1000, options=tuple("12345"))
    query = QueryDecomposer().decompose(item)[2]
    assert query.original == "가" * STEM_PREFIX_CHARS + "\n3"


def test_effective_prefers_rewritten():
    q = OptionQuery(option_no=1, original="원 질의", rewritten="민법 제548조 해제 원상회복")
    assert q.effective == "민법 제548조 해제 원상회복"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"option_no": 0, "original": "q"},
        {"option_no": 6, "original": "q"},
        {"option_no": 1, "original": " "},
        {"option_no": 1, "original": "q", "rewritten": ""},
        {"option_no": 1, "original": "q", "rewritten": "r", "fallback": True},
    ],
)
def test_option_query_rules(kwargs):
    with pytest.raises(ValueError):
        OptionQuery(**kwargs)

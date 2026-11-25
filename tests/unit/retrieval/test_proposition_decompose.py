"""CR-020: 조합형 문항은 보기가 아니라 **명제**로 질의를 나눈다.

조합형은 보기가 "ㄱ, ㄴ"(6자)뿐이라 보기로 질의를 만들면 5개가 사실상 같아진다
(2026 선택형 실패 분석: 틀린 10문항이 전부 조합형, 후보 중앙값 11 대 일반형 17.5).
"""

from __future__ import annotations

from lawqa.retrieval.domain.decomposer import (
    QueryDecomposer,
    followup_queries,
    split_propositions,
)
from lawqa.retrieval.domain.models import ExamItem

COMBO_STEM = """손해배상에 관한 설명 중 옳지 않은 것을 모두 고른 것은?
ㄱ. 첫째 명제의 본문이다.
ㄴ. 둘째 명제의 본문이다.
ㄷ. 셋째 명제의 본문이다.
ㄹ. 넷째 명제의 본문이다."""
COMBO = ExamItem(
    stem=COMBO_STEM, options=("ㄱ", "ㄴ, ㄹ", "ㄱ, ㄴ, ㄷ", "ㄴ, ㄷ, ㄹ", "ㄱ, ㄴ, ㄷ, ㄹ")
)
PLAIN = ExamItem(
    stem="전세권에 관한 설명 중 옳지 않은 것은?",
    options=("전세권 명제 하나", "둘", "셋", "넷", "다섯"),
)


def test_split_propositions_finds_head_and_items() -> None:
    head, props = split_propositions(COMBO_STEM)

    assert head == "손해배상에 관한 설명 중 옳지 않은 것을 모두 고른 것은?"
    assert [m for m, _ in props] == ["ㄱ", "ㄴ", "ㄷ", "ㄹ"]
    assert props[0][1] == "첫째 명제의 본문이다."


def test_plain_stem_has_no_propositions() -> None:
    assert split_propositions(PLAIN.stem)[1] == []


def test_combo_makes_one_query_per_proposition() -> None:
    queries = QueryDecomposer().decompose(COMBO)

    assert len(queries) == 5  # RetrievalResult가 슬롯 1~5를 요구한다
    assert len({q.original for q in queries}) == 5  # 서로 다른 질의
    for slot, mark in enumerate(("ㄱ", "ㄴ", "ㄷ", "ㄹ"), start=1):
        assert f"{mark}. " in queries[slot - 1].original
    # 명제가 4개뿐이면 남는 슬롯은 물음 문장만
    assert queries[4].original == "손해배상에 관한 설명 중 옳지 않은 것을 모두 고른 것은?"


def test_combo_query_does_not_mix_other_propositions() -> None:
    first = QueryDecomposer().decompose(COMBO)[0].original

    assert "첫째" in first
    assert "둘째" not in first and "넷째" not in first


def test_plain_keeps_option_based_queries() -> None:
    queries = QueryDecomposer().decompose(PLAIN)

    assert [q.option_no for q in queries] == [1, 2, 3, 4, 5]
    assert queries[0].original.endswith("전세권 명제 하나")


# ── CR-019: 근거 부족 명제만 재검색 ──
def test_followup_picks_only_propositions_of_insufficient_options() -> None:
    """보기 ②(ㄴ, ㄹ)만 근거 부족이면 ㄴ·ㄹ 질의만 만든다."""
    queries = followup_queries(COMBO, {2})

    assert len(queries) == 2
    joined = " ".join(q.original for q in queries)
    assert "둘째" in joined and "넷째" in joined
    assert "첫째" not in joined and "셋째" not in joined


def test_followup_unions_propositions_across_options() -> None:
    queries = followup_queries(COMBO, {1, 2})  # ㄱ + (ㄴ, ㄹ)

    joined = " ".join(q.original for q in queries)
    assert all(w in joined for w in ("첫째", "둘째", "넷째"))
    assert "셋째" not in joined


def test_followup_is_empty_when_nothing_insufficient() -> None:
    assert followup_queries(COMBO, set()) == []


def test_followup_on_plain_item_reuses_those_options() -> None:
    queries = followup_queries(PLAIN, {3})

    assert len(queries) == 1 and queries[0].option_no == 3
    assert queries[0].original.endswith("셋")

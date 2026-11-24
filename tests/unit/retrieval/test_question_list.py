"""TKT-BE-M2-03: 보기별 목록 → 문항 목록 라운드로빈 합침·중복 제거, 컨텍스트 (ADR-011)."""

from __future__ import annotations

import pytest

from lawqa.retrieval.domain.models import Candidate, OptionQuery, OptionResult, RetrievalResult


def _cand(chunk_id: str, rank: int) -> Candidate:
    return Candidate(chunk_id=chunk_id, doc_id=chunk_id, location="loc", text="t", final_rank=rank)


def _option(no: int, ids: list[str]) -> OptionResult:
    return OptionResult(
        query=OptionQuery(option_no=no, original=f"q{no}"),
        candidates=tuple(_cand(cid, r) for r, cid in enumerate(ids, start=1)),
    )


def _result(lists: list[list[str]]) -> RetrievalResult:
    return RetrievalResult(
        config_name="B", options=tuple(_option(no, ids) for no, ids in enumerate(lists, start=1))
    )


def _ids(cands) -> list[str]:
    return [c.chunk_id for c in cands]


def test_round_robin_takes_each_options_first_then_second():
    r = _result([["a1", "a2"], ["b1", "b2"], ["c1"], ["d1", "d2"], ["e1"]])
    assert _ids(r.question_list()) == ["a1", "b1", "c1", "d1", "e1", "a2", "b2", "d2"]


def test_top5_is_each_options_first_candidate():
    r = _result([[f"{o}{i}" for i in range(1, 5)] for o in "abcde"])
    assert _ids(r.question_list()[:5]) == ["a1", "b1", "c1", "d1", "e1"]


def test_duplicates_keep_first_occurrence_only():
    r = _result([["x", "a2"], ["x", "b2"], ["c1", "x"], ["d1"], ["e1"]])
    assert _ids(r.question_list()) == ["x", "c1", "d1", "e1", "a2", "b2"]


def test_max_len_limits_list():
    r = _result([[f"{o}{i}" for i in range(1, 21)] for o in "abcde"])
    assert len(r.question_list()) == 20
    assert len(r.question_list(max_len=7)) == 7


def test_empty_option_lists_are_skipped():
    r = _result([[], ["b1"], [], [], ["e1", "e2"]])
    assert _ids(r.question_list()) == ["b1", "e1", "e2"]


def test_context_is_union_of_top_k_per_option_in_option_order():
    r = _result([["a1", "a2", "a3"], ["a2", "b2"], ["c1"], [], ["e1", "a1", "e3"]])
    assert _ids(r.context(2)) == ["a1", "a2", "b2", "c1", "e1"]


def test_result_requires_options_1_to_5_in_order():
    with pytest.raises(ValueError):
        RetrievalResult(config_name="A", options=(_option(1, ["a"]), _option(2, ["b"])))
    opts = [_option(no, []) for no in (2, 1, 3, 4, 5)]
    with pytest.raises(ValueError):
        RetrievalResult(config_name="A", options=tuple(opts))


def test_option_result_rejects_unordered_or_duplicate_candidates():
    q = OptionQuery(option_no=1, original="q")
    with pytest.raises(ValueError):
        OptionResult(q, (_cand("a", 2), _cand("b", 1)))
    with pytest.raises(ValueError):
        OptionResult(q, (_cand("a", 1), _cand("a", 2)))
    with pytest.raises(ValueError):
        OptionResult(q, (Candidate("a", "a", "loc", "t"),))
    assert OptionResult(q, (_cand("a", 1), _cand("b", 3))).top(1) == (_cand("a", 1),)

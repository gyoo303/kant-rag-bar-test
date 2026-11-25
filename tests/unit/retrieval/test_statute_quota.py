"""CR-018: 보기별 상위 k_opt 안에 조문을 최소 k_law개 보장한다.

말뭉치가 판례 89%라 조문이 점수 경쟁에서 묻힌다. 필요한 조문이 색인에 있어도 후보에 못 들어오는
문제를 막는 장치다(2026-11-24 재측정 실패 분석).
"""

from __future__ import annotations

import pytest

from lawqa.retrieval.domain.models import Candidate, RetrievalConfig, RetrievalMode
from lawqa.retrieval.infrastructure.retrievers import StatuteQuotaRetriever, is_statute


def _config(**over) -> RetrievalConfig:
    params = dict(
        name="A",
        mode=RetrievalMode.A,
        use_rewrite=False,
        n_vec=20,
        n_bm25=20,
        n_fuse=20,
        k_opt=4,
        rrf_c=60,
        weights=(0.5, 0.5),
    )
    return RetrievalConfig(**{**params, **over})  # type: ignore[arg-type]


def _cand(chunk_id: str, rank: int) -> Candidate:
    doc_id = chunk_id.split("#")[0]
    return Candidate(
        chunk_id=chunk_id,
        doc_id=doc_id,
        location=doc_id,
        text=f"본문 {chunk_id}",
        final_rank=rank,
    )


def _prec(n: int, rank: int) -> Candidate:
    return _cand(f"prec:{n}#HOLDING#1", rank)


def _law(no: int, rank: int) -> Candidate:
    return _cand(f"law:민법:{no}-0#ARTICLE#1", rank)


class _Fixed:
    def __init__(self, items: list[Candidate]) -> None:
        self.items = items
        self.calls = 0

    def retrieve(self, query: str) -> list[Candidate]:
        self.calls += 1
        return list(self.items)


def _wrap(base: list[Candidate], statutes: list[Candidate], *, k_law: int = 1, k_opt: int = 4):
    inner, extra = _Fixed(base), _Fixed(statutes)
    return StatuteQuotaRetriever(inner, extra, k_law=k_law, k_opt=k_opt), inner, extra


def test_is_statute_distinguishes_law_from_precedent() -> None:
    assert is_statute(_law(507, 1)) and not is_statute(_prec(1, 1))


def test_statute_is_pulled_in_when_top_has_none() -> None:
    """판례만 올라온 경우 조문 전용 검색으로 채우고, 가장 낮은 판례를 밀어낸다."""
    base = [_prec(i, i) for i in range(1, 7)]
    r, _, extra = _wrap(base, [_law(507, 1)])

    out = r.retrieve("혼동")

    top = out[:4]
    assert sum(1 for c in top if is_statute(c)) == 1
    assert top[-1].chunk_id == "law:민법:507-0#ARTICLE#1"  # 승격된 조문
    assert [c.chunk_id for c in top[:3]] == [f"prec:{i}#HOLDING#1" for i in (1, 2, 3)]
    assert extra.calls == 1
    assert [c.final_rank for c in out] == list(range(1, len(out) + 1))  # 순위 재부여


def test_statute_deeper_in_list_is_promoted_without_extra_search() -> None:
    """이미 받은 목록 아래쪽에 조문이 있으면 보충 검색을 하지 않는다."""
    base = [_prec(1, 1), _prec(2, 2), _prec(3, 3), _prec(4, 4), _law(587, 5)]
    r, _, extra = _wrap(base, [_law(201, 1)])

    out = r.retrieve("과실수취권")

    assert sum(1 for c in out[:4] if is_statute(c)) == 1
    assert extra.calls == 0  # 보충 검색 없음


def test_enough_statutes_already_leaves_order_untouched() -> None:
    base = [_law(507, 1), _prec(1, 2), _prec(2, 3), _prec(3, 4)]
    r, _, extra = _wrap(base, [_law(201, 1)])

    assert r.retrieve("혼동") == base
    assert extra.calls == 0


def test_k_law_zero_disables_the_quota() -> None:
    base = [_prec(i, i) for i in range(1, 6)]
    r, _, extra = _wrap(base, [_law(507, 1)], k_law=0)

    assert r.retrieve("질의") == base
    assert extra.calls == 0


def test_no_statute_anywhere_keeps_base_result() -> None:
    """조문이 색인에 없으면 후보를 깎지 않는다(빈손으로 돌아오지 않는다)."""
    base = [_prec(i, i) for i in range(1, 6)]
    r, _, _ = _wrap(base, [])

    assert r.retrieve("질의") == base


def test_two_statutes_promoted_when_k_law_is_two() -> None:
    base = [_prec(i, i) for i in range(1, 7)]
    r, _, _ = _wrap(base, [_law(507, 1), _law(201, 2)], k_law=2)

    top = r.retrieve("질의")[:4]

    assert sum(1 for c in top if is_statute(c)) == 2
    assert [c.chunk_id for c in top[:2]] == ["prec:1#HOLDING#1", "prec:2#HOLDING#1"]


def test_promoted_statute_is_not_duplicated() -> None:
    """보충 검색이 이미 있는 청크를 돌려줘도 중복으로 넣지 않는다."""
    base = [_prec(1, 1), _prec(2, 2), _prec(3, 3), _prec(4, 4), _law(507, 5)]
    r, _, _ = _wrap(base, [_law(507, 1)])

    out = r.retrieve("혼동")

    assert len(out) == len(base)
    assert len({c.chunk_id for c in out}) == len(out)


def test_config_rejects_k_law_above_k_opt() -> None:
    with pytest.raises(ValueError, match="k_law"):
        _config(k_law=5)


def test_k_law_is_part_of_comparable_key() -> None:
    """INV-08: 구성끼리 같아야 하는 값에 들어간다."""
    assert _config(k_law=1).comparable_key != _config(k_law=2).comparable_key

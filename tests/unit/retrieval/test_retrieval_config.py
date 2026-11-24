"""TKT-BE-M2-03: RetrievalConfig 규칙과 comparable_key (INV-08)."""

from __future__ import annotations

import pytest

from lawqa.retrieval.domain.models import RetrievalConfig, RetrievalMode

BASE = {"n_vec": 20, "n_bm25": 20, "n_fuse": 20, "k_opt": 4, "rrf_c": 60, "weights": (0.5, 0.5)}


def _config(name, mode, rewrite=False, **over):
    return RetrievalConfig(name=name, mode=mode, use_rewrite=rewrite, **{**BASE, **over})


def test_all_four_configs_share_comparable_key():
    configs = [
        _config("A", RetrievalMode.A),
        _config("B", RetrievalMode.B),
        _config("C", RetrievalMode.C),
        _config("C+R", RetrievalMode.C, rewrite=True),
    ]
    assert len({c.comparable_key for c in configs}) == 1


def test_comparable_key_changes_with_k_opt():
    a = _config("A", RetrievalMode.A)
    b = _config("B", RetrievalMode.B, k_opt=5)
    assert a.comparable_key != b.comparable_key


@pytest.mark.parametrize(
    ("name", "mode", "rewrite"),
    [
        ("A", RetrievalMode.B, False),
        ("C+R", RetrievalMode.C, False),
        ("C", RetrievalMode.C, True),
        ("D", RetrievalMode.A, False),
    ],
)
def test_name_mode_rewrite_must_match(name, mode, rewrite):
    with pytest.raises(ValueError):
        _config(name, mode, rewrite)


@pytest.mark.parametrize(
    "over", [{"k_opt": 0}, {"rrf_c": 0}, {"weights": (0.0, 0.0)}, {"weights": (-1.0, 2.0)}]
)
def test_numeric_rules(over):
    with pytest.raises(ValueError):
        _config("B", RetrievalMode.B, **over)

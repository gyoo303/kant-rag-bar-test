"""TKT-BE-M1-02: 시작 전 점검 (US-03, AC-03-1·2). 외부 호출은 가짜 점검기로 대신한다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from lawqa.shared.settings import load_settings
from lawqa.shared.smoke import (
    SAMPLE_DOCS,
    SCALE_NOTE,
    run_smoke,
    summary_lines,
    write_report,
)

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"
FAKE_KEY = "sk-test" + "x" * 30


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 24, 9, 30, 0).astimezone()


class FakeProbes:
    """모든 점검이 성공하는 가짜. `fail`에 이름을 주면 그 점검만 예외."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise RuntimeError(f"{name} 실패 (key={FAKE_KEY})")

    def generation(self) -> dict[str, Any]:
        self._maybe_fail("generation")
        return {"model_requested": "gpt-6-luna", "model_reported": "gpt-6-luna-2026-05-18"}

    def embedding(self) -> dict[str, Any]:
        self._maybe_fail("embedding")
        return {"model_requested": "text-embedding-3-small", "dimensions": 1536}

    def gpu(self) -> dict[str, Any]:
        self._maybe_fail("gpu")
        return {"cuda_available": True, "device_name": "Fake GPU"}

    def rerank(self, query: str, docs: list[str]) -> dict[str, Any]:
        self._maybe_fail("rerank")
        return {"device": "cuda", "pairs": len(docs), "score_ms": 12, "scores": [0.1, 0.9, 0.0]}

    def bm25_scores(self, query: str, docs: list[str]) -> list[float]:
        self._maybe_fail("bm25")
        return [1.5, 3.2, 0.0]

    def vector_scores(self, query: str, docs: list[str]) -> list[float]:
        self._maybe_fail("vector")
        return [0.41, 0.63, 0.12]


@pytest.fixture
def settings():
    return load_settings("base", config_dir=REPO_CONFIG, env_file=Path("missing.env"), environ={})


def _check(report, name: str):
    return next(c for c in report.checks if c.name == name)


def test_run_smoke_all_probes_ok_records_every_check(settings) -> None:
    report = run_smoke(settings, FakeProbes(), FixedClock())

    names = [c.name for c in report.checks]
    assert names == ["generation", "embedding", "gpu", "rerank", "bm25", "vector", "score_scales"]
    assert report.ok
    assert report.config_sha == settings.config_sha


def test_ac_03_1_generation_and_embedding_record_model_and_success(settings) -> None:
    report = run_smoke(settings, FakeProbes(), FixedClock())

    generation = _check(report, "generation")
    embedding = _check(report, "embedding")
    assert generation.ok and generation.detail["model_requested"] == "gpt-6-luna"
    assert generation.detail["model_reported"]
    assert embedding.ok and embedding.detail["model_requested"] == "text-embedding-3-small"


def test_ac_03_2_bm25_and_vector_scores_recorded_separately_with_scale_note(settings) -> None:
    report = run_smoke(settings, FakeProbes(), FixedClock())

    bm25 = _check(report, "bm25").detail["results"]
    vector = _check(report, "vector").detail["results"]
    assert [r["score"] for r in bm25] == [3.2, 1.5, 0.0]
    assert [r["score"] for r in vector] == [0.63, 0.41, 0.12]
    assert bm25[0]["location"] == SAMPLE_DOCS[1][0]
    assert _check(report, "score_scales").detail["note"] == SCALE_NOTE


def test_run_smoke_one_failure_recorded_and_others_continue(settings) -> None:
    report = run_smoke(settings, FakeProbes(fail={"generation"}), FixedClock())

    generation = _check(report, "generation")
    assert not generation.ok
    assert generation.error and generation.error.startswith("RuntimeError")
    assert _check(report, "embedding").ok
    assert _check(report, "vector").ok
    assert not report.ok


def test_run_smoke_score_count_mismatch_is_error(settings) -> None:
    class ShortProbes(FakeProbes):
        def bm25_scores(self, query: str, docs: list[str]) -> list[float]:
            return [1.0]

    report = run_smoke(settings, ShortProbes(), FixedClock())

    assert not _check(report, "bm25").ok


def test_write_report_never_contains_api_key_and_does_not_overwrite(
    settings, tmp_path: Path
) -> None:
    report = run_smoke(settings, FakeProbes(fail={"embedding"}), FixedClock())

    first = write_report(report, tmp_path, FixedClock())
    second = write_report(report, tmp_path, FixedClock())

    assert first.parent == tmp_path / "smoke"
    assert first.name == "2026-11-24_093000.json"
    assert first != second and first.exists() and second.exists()
    text = first.read_text(encoding="utf-8")
    assert FAKE_KEY not in text
    assert "sk-***" in text
    data = json.loads(text)
    assert data["ok"] is False
    assert data["config_sha"] == settings.config_sha


def test_summary_lines_mark_failures(settings) -> None:
    report = run_smoke(settings, FakeProbes(fail={"gpu"}), FixedClock())

    lines = summary_lines(report)

    assert any(line.startswith("[ERR] gpu") for line in lines)
    assert any(line.startswith("[OK ] embedding") for line in lines)

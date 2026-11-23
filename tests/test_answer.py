from types import SimpleNamespace

import pytest
from conftest import make_rc

import kant_rag.generation.answer as answer_mod
from kant_rag.schemas import AnswerStatus


class FakeLLM:
    def __init__(self, out):
        self.out = out

    def invoke(self, _messages):
        if isinstance(self.out, Exception):
            raise self.out
        return SimpleNamespace(content=self.out)


@pytest.fixture
def patch_llm(monkeypatch):
    def _set(out):
        monkeypatch.setattr(answer_mod, "get_chat_model", lambda *a, **k: FakeLLM(out))
    return _set


def test_ok_with_valid_citation(settings, patch_llm):
    patch_llm('{"answerable": true, "answer": "가능", "cited_chunk_ids": ["D1#a"]}')
    res, info = answer_mod.generate_answer("q", [make_rc("D1#a", 1)], settings)
    assert res.status == AnswerStatus.OK and res.citations[0].chunk_id == "D1#a"


def test_hallucinated_citation_flagged(settings, patch_llm):
    patch_llm('{"answerable": true, "answer": "x", "cited_chunk_ids": ["NOPE#1"]}')
    res, _ = answer_mod.generate_answer("q", [make_rc("D1#a", 1)], settings)
    assert res.status == AnswerStatus.INVALID_CITATION


def test_insufficient_and_errors_are_distinct(settings, patch_llm):
    patch_llm('{"answerable": false, "answer": "정보 부족", "cited_chunk_ids": []}')
    assert answer_mod.generate_answer("q", [make_rc("D1#a", 1)], settings)[0].status == AnswerStatus.INSUFFICIENT
    patch_llm(RuntimeError("timeout"))
    assert answer_mod.generate_answer("q", [make_rc("D1#a", 1)], settings)[0].status == AnswerStatus.GENERATION_ERROR


def test_rerank_gate(settings, patch_llm):
    patch_llm(RuntimeError("should not be called"))
    low = make_rc("D1#a", 1, source="rerank", score=0.01)
    res, info = answer_mod.generate_answer("q", [low], settings, min_rerank_score=0.2)
    assert res.status == AnswerStatus.INSUFFICIENT and info["gate"]

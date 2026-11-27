import pytest
from pydantic import ValidationError

from kant_rag.config import ROOT
from kant_rag.evaluation.dataset import EvalItem
from kant_rag.evaluation.metrics import hit_at_k
from kant_rag.mcq.io import load_bar_evalset


def test_eval_files_load():
    assert load_bar_evalset(ROOT / "eval" / "dev.json").split == "dev"
    assert load_bar_evalset(ROOT / "eval" / "test.json").split == "test"


def test_no_answer_requires_empty_evidence():
    with pytest.raises(ValidationError):
        EvalItem(id="X", split="dev", type="no_answer", question="q", reference_answer="r",
                 evidence=[{"doc_id": "D", "chunk_id": "D#1", "location": "-"}], no_answer_reason="x")


def test_hit_at_5():
    item = EvalItem(id="X", split="test", type="direct", question="q", expected_facts=["f"],
                    reference_answer="r", evidence=[{"doc_id": "D", "chunk_id": "D#6", "location": "-"}])
    rec = {"retrieval": {"final": [{"chunk_id": f"D#{i}"} for i in range(1, 7)]}}
    assert hit_at_k(rec, item, 5) == 0
    assert hit_at_k(rec, item, 6) == 1
    assert hit_at_k({"retrieval": {}}, item) == 0  # 검색 실패 = 0

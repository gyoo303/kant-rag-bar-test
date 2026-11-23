import json

from civil_rag import config
from civil_rag.evaluation import dataset


def _write(tmp_path, split, items, version="test-v1"):
    (tmp_path / f"{split}.json").write_text(json.dumps({"version": version, "items": items}, ensure_ascii=False), encoding="utf-8")


def test_validate_flags_wrong_composition(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path)
    items = [{"id": "T01", "type": "direct", "question": "q", "expected_answer": "O",
              "allowed_evidence": [{"doc_id": "1"}]}]
    _write(tmp_path, "test", items, version="test-draft")
    probs = dataset.validate("test")
    assert any("draft" in p for p in probs)
    assert any("문항 수 1" in p for p in probs)


def test_validate_no_evidence_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path)
    items = [{"id": "N1", "type": "no_evidence", "question": "q", "allowed_evidence": [{"doc_id": "1"}]}]
    _write(tmp_path, "other", items)
    probs = dataset.validate("other")
    assert any("비워야" in p for p in probs)
    assert any("no_evidence_reason" in p for p in probs)

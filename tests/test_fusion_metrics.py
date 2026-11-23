from civil_rag.evaluation.metrics import (
    citation_auto,
    hit_at_k,
    latency_stats,
    no_evidence_correct,
    summarize,
    verdict_correct,
)
from civil_rag.retrieval.fusion import weighted_rrf
from civil_rag.retrieval.tokenize import whitespace_tokenize


def test_weighted_rrf_formula_and_dedup():
    out = dict(weighted_rrf([["a", "b"], ["b", "c"]], [0.5, 0.5], c=60))
    assert set(out) == {"a", "b", "c"}                      # 중복 제거
    assert abs(out["b"] - (0.5 / 62 + 0.5 / 61)) < 1e-12   # 두 목록 합산
    assert abs(out["a"] - 0.5 / 61) < 1e-12
    order = [cid for cid, _ in weighted_rrf([["a", "b"], ["b", "c"]], [0.5, 0.5])]
    assert order[0] == "b"


def test_weighted_rrf_weights_shift_ranking():
    keyword_heavy = [cid for cid, _ in weighted_rrf([["a"], ["b"]], [0.8, 0.2])]
    meaning_heavy = [cid for cid, _ in weighted_rrf([["a"], ["b"]], [0.2, 0.8])]
    assert keyword_heavy[0] == "a" and meaning_heavy[0] == "b"


def test_whitespace_tokenizer_strips_brackets():
    assert whitespace_tokenize("[1] 민법 제750조, (불법행위)") == ["1", "민법", "제750조", "불법행위"]


def _cand(chunk_id, doc_id, section, case_no=""):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "section": section, "metadata": {"case_no": case_no}}


def test_hit_at_k_matching_rules():
    final = [_cand(f"x:{i}", "x", "판례내용") for i in range(5)] + [_cand("625343:판결요지:0", "625343", "판결요지", "2025다212572")]
    assert hit_at_k(final, [{"chunk_id": "625343:판결요지:0"}], k=5) == 0   # 6위라 Hit@5 밖
    assert hit_at_k(final, [{"chunk_id": "625343:판결요지:0"}], k=6) == 1
    top = [_cand("625343:판결요지:1", "625343", "판결요지", "2025다212572")]
    assert hit_at_k(top, [{"doc_id": "625343", "section": "판결요지"}]) == 1
    assert hit_at_k(top, [{"doc_id": "625343", "section": "판시사항"}]) == 0
    assert hit_at_k(top, [{"doc_id": "625343"}]) == 1
    assert hit_at_k(top, [{"case_no": "2025다212572"}]) == 1
    assert hit_at_k([], [{"doc_id": "625343"}]) == 0                          # 검색 실패는 0


def test_verdict_and_no_evidence_rules():
    assert verdict_correct("O", "O", "ok") == 1
    assert verdict_correct("O", "X", "ok") == 0
    assert verdict_correct("O", None, "error") == 0
    assert verdict_correct("서술형 정답", "해당 없음", "ok") is None
    assert no_evidence_correct("정보 부족", "no_evidence") == 1
    assert no_evidence_correct(None, "error") == 0                            # 오류는 거절로 안 셈
    assert no_evidence_correct("O", "ok") == 0


def test_citation_auto():
    assert citation_auto({"status": "ok", "valid_citations": [1], "citation_valid": True}) == 1
    assert citation_auto({"status": "ok", "valid_citations": [1], "citation_valid": False}) == 0
    assert citation_auto({"status": "ok", "valid_citations": [], "citation_valid": True}) == 0


def test_summarize_denominators():
    rows = [
        {"type": "direct", "status": "ok", "hit_at_5": 1, "verdict_auto": 1, "citation_auto": 1, "no_evidence_ok": None, "seconds": 2.0},
        {"type": "paraphrase", "status": "error", "hit_at_5": 0, "verdict_auto": 0, "citation_auto": 0, "no_evidence_ok": None, "seconds": 9.0},
        {"type": "no_evidence", "status": "no_evidence", "hit_at_5": None, "verdict_auto": None, "citation_auto": None, "no_evidence_ok": 1, "seconds": 4.0},
    ]
    s = summarize(rows, has_retrieval=True)
    assert s["hit_at_5"] == (1, 2)
    assert s["no_evidence"] == (1, 1)
    assert s["success"] == 2 and s["errors"] == 1
    assert s["latency"] == latency_stats([2.0, 4.0])                        # 성공 호출만

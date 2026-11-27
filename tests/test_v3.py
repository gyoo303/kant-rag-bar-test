from types import SimpleNamespace

from conftest import make_rc

import kant_rag.generation.llmcall as llmcall_mod
from kant_rag.mcq.context import ChunkGraph, referenced_articles
from kant_rag.mcq.presets import PRESETS, apply_overrides, parse_sets
from kant_rag.mcq.solver import MCQSolver, build_context, rewrite_statement_queries
from kant_rag.retrieval.pipeline import RetrievalMode
from kant_rag.schemas import Chunk
from test_mcq import exam


def _law(doc, art, text):
    return Chunk(chunk_id=f"{doc}#{art}", doc_id=doc, title=doc, text=f"[{doc}] {art}\n{text}",
                 metadata={"doc_type": "statute", "article": art})


def _case(cid, issue):
    return Chunk(chunk_id=cid, doc_id="CASES", title="판례", text=f"[판례] {cid}\n판시사항: {issue}\n본문",
                 metadata={"doc_type": "case"})


def graph():
    cs = [_law("COMM", "제429조", "신주발행무효의 소"),
          _law("COMM", "제430조", "제186조 내지 제189조ㆍ제190조 본문의 규정은 제429조의 소에 관하여 이를 준용한다."),
          _law("COMM", "제186조", "본점소재지 전속관할"), _law("COMM", "제190조", "판결의 효력"),
          _law("COMM", "제187조", "x"), _law("COMM", "제188조", "x"), _law("COMM", "제189조", "x"),
          _case("CASE#2024다1#1", "전제"), _case("CASE#2024다1#2~1", "결론(적극)"), _case("CASE#2024다1#2~2", "결론 계속")]
    return ChunkGraph({c.chunk_id: c for c in cs})


def test_referenced_articles_range():
    assert referenced_articles("제186조 내지 제188조ㆍ제190조 본문") == ["제186조", "제187조", "제188조", "제190조"]


def test_reverse_reference_and_siblings():
    g = graph()
    added = g.expand_references(["COMM#제429조"])
    assert added[0] == "COMM#제430조" and "COMM#제186조" in added and "COMM#제190조" in added
    sib = g.case_siblings(["CASE#2024다1#1"])
    assert [s for s, _ in sib] == ["CASE#2024다1#2~1"] and "결론(적극)" in sib[0][1]


def test_build_context_marks_expansions(settings):
    s = apply_overrides(settings, PRESETS["a34"])
    g = graph()
    per = {"1": [make_rc("COMM#제429조", 1)]}
    per["1"][0].chunk.metadata.update({"doc_type": "statute", "article": "제429조"})
    per["1"][0].chunk.doc_id = "COMM"
    g.by_id["COMM#제429조"] = per["1"][0].chunk
    text, used, info = build_context(per, s.mcq, g)
    assert 'kind="reference"' in text and "COMM#제186조" in used and info["references"]


def test_presets_and_overrides(settings):
    s = apply_overrides(settings, {**PRESETS["c"], **parse_sets(["mcq.fusion_weight=0.3"])})
    assert s.mcq.per_statement_k == 5 and s.optimization.rewrite.enabled and s.mcq.rewrite_queries == 2
    assert s.mcq.sibling_items and s.mcq.prompt_version == "v2" and s.mcq.fusion == "fill_unknown"
    assert s.mcq.fusion_weight == 0.3 and settings.mcq.fusion == "none"  # 원본 불변


def test_multi_query_rewrite_parse(settings, monkeypatch):
    s = apply_overrides(settings, PRESETS["a2"])
    q1 = exam().items[0]

    class LLM:
        def invoke(self, _):
            return SimpleNamespace(content='{"1": {"issue": "불법행위 손해배상", "exception": "예외 판례"}, "2": "단일 질의"}',
                                   response_metadata={"finish_reason": "stop"}, usage_metadata={})

    monkeypatch.setattr(llmcall_mod, "get_chat_model", lambda *a, **k: LLM())
    qs, info = rewrite_statement_queries(q1, s)
    assert qs["1"] == ["불법행위 손해배상", "예외 판례"] and qs["2"] == ["단일 질의"]
    assert set(info["fallback_keys"]) == {"3", "4", "5"}


def test_fusion_fills_only_unknown_with_weight(settings, monkeypatch):
    s = apply_overrides(settings, {"mcq.fusion": "fill_unknown", "mcq.prompt_version": "v2"})
    q1 = exam().items[0]  # 옳지 않은 것, 정답 3
    prompts = []

    class LLM:
        def invoke(self, messages):
            prompts.append(messages)
            if len(prompts) == 1:  # RAG 판단: 3 unknown
                body = ", ".join(f'"{k}": {{"verdict": "{"unknown" if k == "3" else "true"}", "confidence": 0.9, "reason": "r"}}'
                                 for k in "12345")
            else:  # closed-book 보완: 3 false
                body = '"3": {"verdict": "false", "confidence": 0.8, "reason": "지식"}'
            return SimpleNamespace(content='{"judgments": {' + body + '}}', response_metadata={"finish_reason": "stop"},
                                   usage_metadata={})

    class Ret:
        def retrieve(self, q, mode):
            return {"final": [make_rc("D#1", 1, "rerank", 0.9)]}

    monkeypatch.setattr(llmcall_mod, "get_chat_model", lambda *a, **k: LLM())
    rec = MCQSolver(s, retriever=Ret()).solve(q1, RetrievalMode.C)
    assert "사실관계가 진술과 같은지" in prompts[0][0][1]  # 프롬프트 v2
    assert rec["fusion"]["unknown_keys"] == ["3"] and rec["judgments"]["3"]["source"] == "knowledge"
    assert rec["judgments"]["3"]["confidence"] == 0.4 and rec["judgments"]["1"]["source"] == "evidence"
    assert rec["predicted"] == 3 and rec["knowledge_used"] and "3. " in prompts[1][1][1] and "1. " not in prompts[1][1][1]


def test_reverse_only_when_subject():
    from kant_rag.mcq.context import _is_subject
    assert _is_subject("제186조 내지 제189조의 규정은 제429조의 소에 관하여 이를 준용한다.", "제429조")
    assert not _is_subject("제186조 내지 제189조ㆍ제431조의 규정은 제1항의 소에 관하여 준용한다.", "제431조")
    assert not _is_subject("제360조의14의 소에 관하여 준용한다.", "제360조")

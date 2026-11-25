"""개선안 v4: 번호 계산 예비 규칙, 판례 메타, 리라이트 v3 파싱, 날짜 필터, 프리셋."""
import json

import kant_rag.generation.llmcall as llmcall_mod
from kant_rag.config import get_settings
from kant_rag.mcq.presets import PRESETS, apply_overrides
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.mcq.solver import _case_attrs, choose_answer, choose_answer_robust, full_court_cases, \
    rewrite_statement_queries
from kant_rag.schemas import Chunk, RetrievedChunk


def _q23():
    return ExamQuestion(id="X", number=23, stem="옳은 것을 모두 고른 것은?",
                        items={"ㄱ": "a", "ㄴ": "b", "ㄷ": "c", "ㄹ": "d"},
                        options={1: "ㄱ, ㄴ", 2: "ㄱ, ㄷ", 3: "ㄴ, ㄹ", 4: "ㄴ, ㄷ, ㄹ", 5: "ㄱ, ㄴ, ㄷ, ㄹ"})


def _j(v, c=1.0):
    return StatementJudgment(verdict=v, confidence=c, reason="", cited_chunk_ids=[])


def test_fallback_picks_fewest_flips_when_all_zero():
    q = _q23()
    js = {"ㄱ": _j("false"), "ㄴ": _j("true"), "ㄷ": _j("true"), "ㄹ": _j("false")}
    best, scores = choose_answer(q, js)
    assert max(scores.values()) == 0 and best == 1          # 기존: 동점 → ①
    best, _, info = choose_answer_robust(q, js)
    assert best == 4 and info["inconsistent"] and info["flipped"] == ["ㄹ"]


def test_fallback_noop_when_consistent():
    q = _q23()
    js = {"ㄱ": _j("false"), "ㄴ": _j("true"), "ㄷ": _j("true"), "ㄹ": _j("true")}
    assert choose_answer(q, js)[0] == choose_answer_robust(q, js)[0] == 4
    assert not choose_answer_robust(q, js)[2]["inconsistent"]


def _case(cid, text, decided="20240718", case_no="2018스724"):
    return Chunk(chunk_id=cid, doc_id="CASES-SC", title="대법원", text=text, section="s", line_start=1, line_end=1,
                 metadata={"doc_type": "case", "decided": decided, "case_no": case_no})


def test_case_meta_full_court():
    a = _case("CASE#2018스724#1~1", "판시사항 … [다수의견] 과거 양육비 …")
    b = _case("CASE#2010다1#1", "일반 판결", "20100101", "2010다1")
    fc = full_court_cases({a.chunk_id: a, b.chunk_id: b})
    assert fc == {"2018스724"}
    assert _case_attrs(a, fc) == ' decided="2024-07-18" full_court="true"'
    assert _case_attrs(b, fc) == ' decided="2010-01-01"'


def test_rewrite_v3_party_query(monkeypatch):
    s = apply_overrides(get_settings(), PRESETS["d"])
    q = _q23()
    out = {k: {"issue": f"{k} 쟁점", "exception": f"{k} 예외", "party": "" if k == "ㄱ" else f"{k} 지위"} for k in q.items}
    monkeypatch.setattr(llmcall_mod, "get_chat_model", lambda *a, **k: _Fake(json.dumps(out, ensure_ascii=False)))
    queries, info = rewrite_statement_queries(q, s)
    assert info["prompt"] == "v3-party"
    assert queries["ㄱ"] == ["ㄱ 쟁점", "ㄱ 예외"] and queries["ㄴ"] == ["ㄴ 쟁점", "ㄴ 예외", "ㄴ 지위"]


class _Msg:
    def __init__(self, t):
        self.content = t
        self.response_metadata = {"finish_reason": "stop"}
        self.usage_metadata = {}


class _Fake:
    def __init__(self, t):
        self.t = t

    def invoke(self, _):
        return _Msg(self.t)


def test_date_filter():
    from kant_rag.retrieval.pipeline import Retriever
    r = Retriever.__new__(Retriever)
    r.s = apply_overrides(get_settings(), {"retrieval.case_date_to": 20231231})
    new = RetrievedChunk(chunk=_case("CASE#A#1", "x", "20240718"), score=1, rank=1, source="rerank")
    old = RetrievedChunk(chunk=_case("CASE#B#1", "y", "20200101", "B"), score=0.9, rank=2, source="rerank")
    kept = r._date_filter([new, old], 5)
    assert [x.chunk.chunk_id for x in kept] == ["CASE#B#1"] and kept[0].rank == 1


def test_presets_v3_unchanged_and_d():
    assert "mcq.answer_fallback" not in PRESETS["v3"] and "mcq.case_meta" not in PRESETS["c"]
    s = apply_overrides(get_settings(), PRESETS["d"])
    assert s.mcq.answer_fallback and s.mcq.case_meta and s.mcq.prompt_version == "v3" and s.mcq.fusion == "none"
    assert apply_overrides(get_settings(), PRESETS["dc"]).mcq.fusion == "fill_unknown"

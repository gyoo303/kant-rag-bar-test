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
    assert s.mcq.answer_fallback and s.mcq.case_meta and s.mcq.prompt_version == "v4" and s.mcq.fusion == "none" and s.mcq.tie_rejudge and s.mcq.original_query
    assert apply_overrides(get_settings(), PRESETS["dc"]).mcq.fusion == "fill_unknown"


# ---------- 적대적 변형본 분석 반영 ----------
from kant_rag.mcq.solver import MCQSolver, tied_options  # noqa: E402


def test_tied_options():
    assert tied_options({1: 0.005, 3: 1.0, 5: 1.0}) == [3, 5]
    assert tied_options({1: 0.2, 2: 0.9}) == [2]
    assert tied_options({1: 0.0, 2: 0.0}) == []


def test_restated_field_parsed():
    j = StatementJudgment.model_validate({"restated": "소멸한다", "verdict": "true", "confidence": 0.9, "reason": "r"})
    assert j.restated == "소멸한다"


def _single():
    return ExamQuestion(id="S", number=55, stem="옳은 것은?", options={i: f"진술{i}" for i in range(1, 6)})


def test_tie_rejudge_resolves(monkeypatch):
    s = apply_overrides(get_settings(), PRESETS["d"])
    solver = MCQSolver(s, retriever=object())
    q = _single()
    js = {str(i): _j("false", 1.0) for i in range(1, 6)}
    js["3"], js["5"] = _j("true", 1.0), _j("true", 1.0)
    _, scores = choose_answer(q, js)
    rec = {"judgments": {k: v.model_dump() for k, v in js.items()}, "option_scores": scores, "predicted": 3,
           "status": "ok", "timing_ms": {}}
    again = {"judgments": {"3": {"verdict": "false", "confidence": 0.9, "reason": "단서 대상 아님"},
                           "5": {"verdict": "true", "confidence": 0.95, "reason": "조문"}}}
    seen = {}

    def fake_llm(*a, **k):
        seen["user"] = a[2][1][1]
        return json.dumps(again, ensure_ascii=False), [{"finish_reason": "stop"}]
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", fake_llm)
    out = solver._tiebreak(q, rec, 0.0, "sys", "<doc/>", [])
    assert out["tiebreak"]["tied"] == [3, 5] and out["tiebreak"]["keys"] == ["3", "5"]
    assert out["predicted"] == 5 and out["status"] == "ok" and "③, ⑤" in seen["user"]


def test_fusion_min_conf(monkeypatch):
    s = apply_overrides(get_settings(), PRESETS["dc"])
    solver = MCQSolver(s, retriever=object())
    q = _single()
    js = {str(i): _j("false", 0.9) for i in range(1, 6)}
    js["1"] = _j("unknown", 0.0)
    js["2"] = _j("unknown", 0.0)
    rec = {"judgments": {k: v.model_dump() for k, v in js.items()}, "predicted": None, "status": "ok", "timing_ms": {}}
    kb = {"judgments": {"1": {"verdict": "true", "confidence": 0.95, "reason": "a"},
                        "2": {"verdict": "true", "confidence": 0.41, "reason": "b"}}}
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm",
                        lambda *a, **k: (json.dumps(kb, ensure_ascii=False), [{"finish_reason": "stop"}]))
    out = solver._fuse(q, rec, 0.0)
    assert list(out["fusion"]["filled"]) == ["1"] and "2" in out["fusion"]["skipped_low_conf"]
    assert out["judgments"]["2"]["verdict"] == "unknown"


def test_variant_compare_flags():
    from kant_rag.mcq.variant import compare
    base = dict(id="V", number=1, stem="옳은 것은?", answer=1)
    o = ExamQuestion(**base, options={1: "기간은 5년이다", 2: "b", 3: "c", 4: "d", 5: "청산이 끝나야 소멸한다"})
    v = ExamQuestion(**base, options={1: "기간은 6년이다", 2: "b", 3: "c", 4: "d", 5: "청산이 끝나야 소멸하지 않는 것이 아니다"})
    rows = {r["key"]: r for r in compare({1: o}, {1: v})}
    assert set(rows) == {"1", "5"}
    assert rows["1"]["number_changed"] and rows["5"]["double_negation"] and rows["5"]["negation_changed"]
def test_v4_alias():
    assert PRESETS["v4"] == PRESETS["d"]

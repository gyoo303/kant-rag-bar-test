"""v5: 방어 기능 단위 테스트 + 프리셋별 끝까지 도는 통합 테스트 (가짜 검색기·가짜 LLM)."""
import json

import pytest

from kant_rag.config import get_settings
from kant_rag.mcq.defense import (
    Calibrator,
    asof_date,
    cross_refs,
    fit_calibration,
    out_of_corpus,
    quote_supported,
)
from kant_rag.mcq.evaluate import mcnemar_exact
from kant_rag.mcq.presets import PRESETS, apply_overrides
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.mcq.solver import MCQSolver, exact_match_exists, tied_options
from kant_rag.retrieval.pipeline import RetrievalMode
from kant_rag.schemas import Chunk, RetrievedChunk


def test_asof_date():
    assert asof_date("2023. 1. 1. 당시의 판례에 의함") == "20230101"
    assert asof_date("2022. 12. 31. 현재 및 2023.3.5. 기준") == "20230305"
    assert asof_date("2023. 1. 1. 매매계약을 체결하였다") is None


def test_out_of_corpus():
    titles = {"민법", "상법", "어음법"}
    text = "｢수표법｣에 따라 … ｢민법｣ 제750조 … 이자제한법상 최고이자율"
    assert out_of_corpus(text, titles) == ["수표법", "이자제한법"]
    assert out_of_corpus("약관규제법 위반", {"약관의 규제에 관한 법률"}) == []


def test_cross_refs():
    keys = ["ㄱ", "ㄴ", "ㄷ"]
    assert cross_refs("ㄴ", "ㄱ의 경우에 이어 丙이 변제한 뒤", keys) == ["ㄱ"]
    assert cross_refs("ㄷ", "위 ㄴ에서 X 토지가 미등기라면", keys) == ["ㄴ"]
    assert cross_refs("ㄱ", "ㄱ의 경우", keys) == []


def test_quote_supported():
    texts = ["[판례] … 청산사무가 완료되어야 비로소 그 당사자능력이 소멸한다."]
    assert quote_supported("청산사무가 완료되어야 비로소 당사자능력이 소멸", texts) is False  # '그' 빠짐 → 원문 그대로 아님
    assert quote_supported("청산사무가 완료되어야 비로소 그 당사자능력이 소멸한다", texts) is True
    assert quote_supported("짧음", texts) is None


def test_calibration_monotone_and_no_zero():
    samples = [("evidence", 1.0, True)] * 40 + [("evidence", 1.0, False)] * 2 + \
              [("evidence", 0.9, True)] * 6 + [("evidence", 0.9, False)] * 4
    cal = Calibrator(fit_calibration(samples))
    assert cal(1.0) <= 0.98 and cal(0.9) < cal(1.0)
    f = cal.support()
    j = StatementJudgment(verdict="true", confidence=1.0, reason="")
    assert 0 < f(j, False) < 0.1


def test_mcnemar_and_ratio():
    assert mcnemar_exact(4, 1) == pytest.approx(0.375)
    assert mcnemar_exact(0, 0) == 1.0
    assert tied_options({1: 0.6, 2: 0.35, 3: 0.01}, ratio=0.5) == [1, 2]


def test_exact_match():
    q = ExamQuestion(id="X", number=1, stem="옳은 것을 모두 고른 것은?", items={"ㄱ": "a", "ㄴ": "b"},
                     options={1: "ㄱ", 2: "ㄴ", 3: "ㄱ, ㄴ", 4: "ㄱ", 5: "ㄴ"})
    t = StatementJudgment(verdict="true", confidence=1.0, reason="")
    f = StatementJudgment(verdict="false", confidence=1.0, reason="")
    assert exact_match_exists(q, {"ㄱ": t, "ㄴ": f})
    q2 = q.model_copy(update={"options": {1: "ㄱ", 2: "ㄱ", 3: "ㄱ", 4: "ㄱ", 5: "ㄱ"}})
    assert not exact_match_exists(q2, {"ㄱ": f, "ㄴ": f})


# ---------- 통합: 프리셋별로 solve() 를 끝까지 ----------
def _chunks():
    law = Chunk(chunk_id="LAW-CIVIL#제706조", doc_id="LAW-CIVIL", title="민법",
                text="[민법] 제706조\n조합계약으로 업무집행자를 정하지 아니한 경우에는 조합원의 3분의 2 이상의 찬성으로써 이를 선임한다.",
                section="s", line_start=1, line_end=1, metadata={"doc_type": "statute", "article": "제706조"})
    case = Chunk(chunk_id="CASE#92다23087#1", doc_id="CASES-SC", title="대법원 92다23087",
                 text="[판례] 대법원 19921222 92다23087 판결요지 [1]\n청산사무가 완료되어야 비로소 그 당사자능력이 소멸한다.",
                 section="s", line_start=1, line_end=1,
                 metadata={"doc_type": "case", "case_no": "92다23087", "decided": "19921222"})
    return {c.chunk_id: c for c in (law, case)}


class _FakeVector:
    def __init__(self, by_id):
        self.chunks_by_id = by_id


class _FakeRetriever:
    def __init__(self):
        self.vector = _FakeVector(_chunks())
        self.calls = []

    def retrieve(self, query, mode, date_to=None):
        self.calls.append((query, date_to))
        return {"final": [RetrievedChunk(chunk=c, score=1.0 - i * 0.1, rank=i + 1, source="rerank")
                          for i, c in enumerate(self.vector.chunks_by_id.values())]}


def _fake_llm(*args, **kwargs):
    messages = args[2]
    system, user = messages[0][1], messages[1][1]
    if "검색용 질의" in system:  # 리라이트
        keys = [ln.split(".")[0] for ln in user.split("[진술]")[1].strip().splitlines() if ln.strip()]
        out = {k: {"issue": f"{k} 쟁점", "exception": f"{k} 예외", "party": ""} for k in keys}
        return json.dumps(out, ensure_ascii=False), [{"finish_reason": "stop"}]
    js = {
        "ㄱ": {"verdict": "true", "confidence": 1.0, "reason": "조문", "cited_chunk_ids": ["LAW-CIVIL#제706조"],
              "quote": "조합원의 3분의 2 이상의 찬성으로써 이를 선임한다"},
        "ㄴ": {"verdict": "true", "confidence": 0.95, "reason": "판례", "cited_chunk_ids": ["CASE#92다23087#1"],
              "quote": "원문에 없는 문장을 인용함"},
    }
    return json.dumps({"judgments": js}, ensure_ascii=False), [{"finish_reason": "stop"}]


@pytest.mark.parametrize("preset", ["v3", "v4", "v5"])
def test_solve_end_to_end(monkeypatch, preset):
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", _fake_llm)
    s = apply_overrides(get_settings(), PRESETS[preset])
    r = _FakeRetriever()
    solver = MCQSolver(s, retriever=r)
    q = ExamQuestion(id="E", number=47, stem="2023. 1. 1. 당시의 판례에 의함. ｢수표법｣과 조합에 관한 설명 중 옳은 것을 모두 고른 것은?",
                     items={"ㄱ": "업무집행자는 조합원 3분의 2 이상 찬성으로 선임한다.", "ㄴ": "ㄱ의 경우에 이어 청산이 끝나야 소멸한다."},
                     options={1: "ㄱ", 2: "ㄴ", 3: "ㄱ, ㄴ", 4: "ㄱ", 5: "ㄴ"}, answer=3)
    rec = solver.solve(q, RetrievalMode.C, "t")
    assert rec["status"] in ("ok", "invalid_citation") and rec["predicted"] == 3
    if preset == "v5":
        assert rec["asof"] == "20230101" and all(d == "20230101" for _, d in r.calls)
        assert rec["out_of_corpus"] == ["수표법"] and rec["cross_refs"] == {"ㄴ": ["ㄱ"]}
        assert rec["quote_check"] == {"ㄱ": True, "ㄴ": False}
        assert rec["judgments"]["ㄴ"]["confidence"] == pytest.approx(0.95 * 0.85, abs=1e-3)
    else:
        assert "asof" not in rec and "quote_check" not in rec and all(d is None for _, d in r.calls)


def test_blank_form_and_regrade(tmp_path):
    from kant_rag.mcq.evaluate import regrade_run
    from kant_rag.mcq.parse import parse_exam_text
    from kant_rag.mcq.solver import choose_answer
    text = """문  56.
  설명 중 각 괄호 안에 들어갈 말을 올바르게 나열한 것은?
ㄱ. 압류는 ( A ).
ㄴ. 피보전채권이 될 수 ( B ).
  A          B
    ① 허용되지 않는다  있다
    ② 허용된다     없다
    ③ 허용된다     있다
    ④ 허용되지 않는다  없다
    ⑤ 허용된다  있다
"""
    q = parse_exam_text(text, "T")[0]
    assert q.form == "blank" and q.blank_items == {"A": "ㄱ", "B": "ㄴ"}
    assert set(q.statements()) == {"A1", "A2", "B1", "B2"} and "[허용된다]" in q.statements()["A2"]
    t = StatementJudgment(verdict="true", confidence=0.9, reason="")
    f = StatementJudgment(verdict="false", confidence=0.9, reason="")
    best, _ = choose_answer(q, {"A1": f, "A2": t, "B1": t, "B2": f})
    assert best in (3, 5)  # ③·⑤ 같은 조합 (시험지 오류 대비, 동점이면 작은 번호)
    d = tmp_path / "run"
    d.mkdir()
    rec = {"number": 56, "config": "hybrid_rerank", "predicted": 3, "status": "ok", "eval": {"kind": "mcq"},
           "judgments": {"A2": t.model_dump(), "A1": f.model_dump(), "B1": t.model_dump(), "B2": f.model_dump()}}
    (d / "records.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    r = regrade_run(d, {56: q.model_copy(update={"answer": 3})})
    assert r["correct"] == 1 and r["statements"]["correct"] == 4

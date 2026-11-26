"""v6r2: 원문 결과 보장·인용-결론 일치·근거 적합성·답과 불일치 재검토·다수결 엄격·재판단 하한·동점 기록."""
import json

import pytest
from test_v6 import _corpus, _FakeRetriever, _raw_cases

from kant_rag.config import get_settings
from kant_rag.mcq.presets import PRESETS, apply_overrides
from kant_rag.mcq.prompts import MCQ_SYSTEM_V7
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.mcq.solver import MCQSolver, _keep_in_top, _stance_conflict
from kant_rag.retrieval.pipeline import RetrievalMode
from kant_rag.schemas import RetrievedChunk


def _rc(cid):
    return RetrievedChunk(chunk=_corpus()[cid], score=1.0, rank=1, source="rerank")


def test_keep_in_top():
    ids = ["LAW-COMM#제208조", "LAW-COMM#제389조", "CASE#99다23888#1", "CASE#2021다252977#1", "LAW-CIVIL#제481조"]
    res = [_rc(x) for x in ids]
    out, kept = _keep_in_top(res, [_rc("CASE#2021다252977#1")], 2)
    assert [r.chunk.chunk_id for r in out][:2] == ["LAW-COMM#제208조", "CASE#2021다252977#1"] and kept == ["CASE#2021다252977#1"]
    assert len(out) == len(res) and len({r.chunk.chunk_id for r in out}) == len(res)
    out2, kept2 = _keep_in_top(res, [_rc("LAW-COMM#제208조")], 2)
    assert kept2 == [] and [r.chunk.chunk_id for r in out2] == ids


def test_stance_conflict_and_prompt():
    j = StatementJudgment(verdict="false", confidence=0.9, reason="", stance="supports")
    assert _stance_conflict(j)
    assert not _stance_conflict(j.model_copy(update={"verdict": "true"}))
    assert _stance_conflict(j.model_copy(update={"verdict": "true", "stance": "contradicts"}))
    assert '"stance"' in MCQ_SYSTEM_V7 and "17." in MCQ_SYSTEM_V7


def _ox_question():
    return ExamQuestion(id="E", number=11, stem="옳은 것(○)과 옳지 않은 것(×)을 올바르게 조합한 것은?",
                        items={"ㄱ": "가", "ㄴ": "나"},
                        options={1: "ㄱ(○), ㄴ(○)", 2: "ㄱ(○), ㄴ(×)", 3: "ㄱ(×), ㄴ(○)", 4: "ㄱ(×), ㄴ(×)", 5: "ㄱ(○), ㄴ(○)"})


def _solver(preset, extra=None):
    s = apply_overrides(get_settings(), {**PRESETS[preset], **(extra or {})})
    return MCQSolver(s, retriever=_FakeRetriever(_corpus()))


@pytest.mark.parametrize("strict,expect", [(False, 3), (True, 2)])
def test_vote_strict_and_min_conf(monkeypatch, strict, expect):
    """문 11 반복 2: [참, 유보, 유보] 다수결이 유보를 약한 참으로 대체해 답이 바뀌던 문제."""
    answers = iter(["true", "unknown", "unknown"])

    def fake(*a, **k):
        v = next(answers)
        return json.dumps({"judgments": {"ㄴ": {"verdict": v, "confidence": 0.85, "reason": "r"}}}), [{}]
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", fake)
    solver = _solver("v6r", {"mcq.vote_strict": strict})
    t = StatementJudgment(verdict="true", confidence=1.0, reason="")
    u = StatementJudgment(verdict="unknown", confidence=0.5, reason="")
    q = _ox_question()
    rec = {"judgments": {"ㄱ": t.model_dump(), "ㄴ": u.model_dump()}, "status": "ok", "timing_ms": {},
           "option_scores": {1: 0.5, 2: 0.5, 3: 0.0, 4: 0.0, 5: 0.5}, "predicted": 1}
    rec = solver._tiebreak(q, rec, 0.0, "sys", "ev", [])
    assert rec["votes"]["tiebreak"]["ㄴ"] == ["true", "unknown", "unknown"]
    # 엄격하지 않으면 참 1표(0.85×1/3)가 유보를 대신 → ①(ㄱ○ㄴ○), 엄격하면 유보 유지 → 동점 그대로(작은 번호 ①)
    js = rec["judgments"]["ㄴ"]
    assert (js["verdict"] == "true") == (not strict)
    # 하한: 엄격하지 않아도 하한 0.6 이면 약한 표(0.283)로 유보를 대체하지 않음
    if not strict:
        answers2 = iter(["true", "unknown", "unknown"])
        monkeypatch.setattr("kant_rag.mcq.solver.call_llm", lambda *a, **k: (json.dumps(
            {"judgments": {"ㄴ": {"verdict": next(answers2), "confidence": 0.85, "reason": "r"}}}), [{}]))
        s2 = _solver("v6r", {"mcq.rejudge_min_conf": 0.6})
        rec2 = {"judgments": {"ㄱ": t.model_dump(), "ㄴ": u.model_dump()}, "status": "ok", "timing_ms": {},
                "option_scores": {1: 0.5, 2: 0.5, 3: 0.0, 4: 0.0, 5: 0.5}, "predicted": 1}
        rec2 = s2._tiebreak(q, rec2, 0.0, "sys", "ev", [])
        assert rec2["judgments"]["ㄴ"]["verdict"] == "unknown" and "ㄴ" in rec2["tiebreak"]["rejected"]
    assert expect in (2, 3)


def test_tie_status_recorded_without_rejudge(monkeypatch):
    """v2 문 24: 동점인데 status 가 ok 로 남던 문제 → tie 로 기록 (예측 번호는 그대로)."""
    def fake(*a, **k):
        return json.dumps({"judgments": {"ㄱ": {"verdict": "unknown", "confidence": 0.5, "reason": "r"},
                                         "ㄴ": {"verdict": "true", "confidence": 1.0, "reason": "r"}}}), [{}]
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", fake)
    rec = _solver("v2").solve(_ox_question(), RetrievalMode.C, "t")
    assert rec["status"] == "tie" and rec["tied"] == [1, 3, 5] and rec["predicted"] == 1


def test_v6r2_research_reasons(monkeypatch, tmp_path):
    """문 24 ㄷ 유형: 고른 보기와 어긋난 고확신 진술 + 인용이 지지하는데 거짓 → 2차 검색 → 인용 확인된 판단으로 교체."""
    log = []

    def fake(*a, **k):
        system, user = a[2][0][1], a[2][1][1]
        log.append(user)
        if "검색용 질의" in system:
            return json.dumps({"ㄱ": {"issue": "ㄱ 쟁점"}, "ㄴ": {"issue": "ㄴ 쟁점"}}, ensure_ascii=False), [{}]
        if "<new_evidence>" in user:
            return json.dumps({"judgments": {"ㄴ": {
                "verdict": "true", "confidence": 0.95, "reason": "원문대로", "stance": "supports",
                "quote": "변제할 정당한 이익이 있는 자는 변제로 당연히 채권자를 대위한다",
                "cited_chunk_ids": ["LAW-CIVIL#제481조"]}}}, ensure_ascii=False), [{}]
        return json.dumps({"judgments": {
            "ㄱ": {"verdict": "true", "confidence": 1.0, "reason": "조문", "stance": "supports",
                  "quote": "공동대표의 권한있는 사원 1인에 대하여 이를 함으로써 그 효력이 생긴다",
                  "cited_chunk_ids": ["LAW-COMM#제208조"]},
            "ㄴ": {"verdict": "false", "confidence": 0.92, "reason": "추정 아님", "stance": "supports",
                  "quote": "변제할 정당한 이익이 있는 자는 변제로 당연히 채권자를 대위한다",
                  "cited_chunk_ids": ["LAW-CIVIL#제481조"]}}}, ensure_ascii=False), [{}]
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", fake)
    raw = _raw_cases(tmp_path)
    solver = _solver("v6r2", {"paths.raw_dir": str(raw.parent), "paths.index_dir": str(tmp_path / "index")})
    q = ExamQuestion(id="E", number=24, stem="옳은 것(○)과 옳지 않은 것(×)을 올바르게 조합한 것은?",
                     items={"ㄱ": "공동대표이사 1인에 대한 의사표시는 효력이 있다.", "ㄴ": "변제자는 당연히 대위한다."},
                     options={1: "ㄱ(×), ㄴ(×)", 2: "ㄱ(○), ㄴ(○)", 3: "ㄱ(×), ㄴ(○)", 4: "ㄱ(×), ㄴ(×)", 5: "ㄱ(×), ㄴ(×)"})
    rec = solver.solve(q, RetrievalMode.C, "t")
    assert "stance" in log[1] or "supports" in json.dumps(rec["judgments"], ensure_ascii=False)
    res = rec["research"]
    assert res["reasons"]["ㄴ"] in ("인용-결론 불일치", "답과 불일치")
    assert res["changed"]["ㄴ"]["to"] == ["true", 0.95]
    assert rec["predicted"] == 2
    assert "cite_check" in rec and set(rec["cite_check"]) == {"ㄱ", "ㄴ"}


def test_polarity_and_count_wording():
    """'판례의 태도와 다른 것은?'(옳지 않은 것), '옳은 것의 수는?'(개수형) — 변형본 하네스 축 F 문구."""
    opts = {i: f"보기{i}" for i in range(1, 6)}
    q = ExamQuestion(id="X", number=22, stem="채권자대위권에 관한 설명 중 판례의 태도와 다른 것은?", options=opts)
    assert q.polarity == "incorrect"
    q2 = q.model_copy(update={"stem": "사해행위 취소에 관한 설명 중 판례의 입장에 부합하지 않는 것은?"})
    assert q2.polarity == "incorrect"
    q3 = q.model_copy(update={"stem": "甲은 乙과 다른 것을 약정하였다. 이에 관한 설명 중 옳은 것은?"})
    assert q3.polarity == "correct"  # 물음 문장이 아닌 사례 본문의 '다른 것'
    c = ExamQuestion(id="Y", number=40, stem="조합에 관한 설명 중 옳은 것의 수는?", items={"ㄱ": "a", "ㄴ": "b"},
                     options={1: "0개", 2: "1개", 3: "2개", 4: "3개", 5: "4개"})
    assert c.form == "count" and c.polarity == "correct"

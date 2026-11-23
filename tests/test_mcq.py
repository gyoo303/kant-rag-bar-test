from pathlib import Path
from types import SimpleNamespace

from conftest import make_rc

import kant_rag.mcq.solver as solver_mod
from kant_rag.mcq.io import import_exam, split_exam
from kant_rag.mcq.schemas import StatementJudgment
from kant_rag.mcq.solver import MCQSolver, choose_answer
from kant_rag.retrieval.pipeline import RetrievalMode

FIX = Path(__file__).parent / "fixtures"


def exam():
    return import_exam(FIX / "synthetic_exam.txt", FIX / "synthetic_answers.csv", "t", "t", "T")


def J(v, c=0.9):
    return StatementJudgment(verdict=v, confidence=c, reason="r")


def test_parse_forms_and_answers():
    q1, q2 = exam().items
    assert (q1.form, q1.polarity, q1.answer) == ("single", "incorrect", 3)
    assert (q2.form, q2.polarity, q2.answer) == ("combination", "correct", 3)
    assert set(q2.items) == {"ㄱ", "ㄴ", "ㄷ"} and q2.options[3] == "ㄱ, ㄷ"


def test_choose_single_incorrect():
    q1 = exam().items[0]
    js = {"1": J("true"), "2": J("true"), "3": J("false"), "4": J("true"), "5": J("true")}
    assert choose_answer(q1, js)[0] == 3


def test_choose_combination():
    q2 = exam().items[1]
    assert choose_answer(q2, {"ㄱ": J("true"), "ㄴ": J("false"), "ㄷ": J("true")})[0] == 3


def test_all_unknown_is_insufficient():
    q1 = exam().items[0]
    assert choose_answer(q1, {k: J("unknown") for k in "12345"})[0] is None


def test_split_is_deterministic():
    a = split_exam(exam(), seed=1, n_dev=1, n_test=1)
    b = split_exam(exam(), seed=1, n_dev=1, n_test=1)
    assert [q.number for q in a["dev"]] == [q.number for q in b["dev"]]
    assert {q.split for q in a["test"]} == {"test"}


class FakeRetriever:
    def retrieve(self, query, mode):
        return {"final": [make_rc("LAW#제766조", 1, "rerank", 0.9), make_rc("LAW#제750조", 2, "rerank", 0.5)]}


def test_solver_end_to_end_without_answer_leak(settings, monkeypatch):
    q1 = exam().items[0]
    q1.evidence = [{"doc_id": "LAW", "chunk_id": "LAW#제766조", "location": "SENTINEL-EVIDENCE"}]
    q1.statement_labels = {"3": False}
    seen = {}

    class FakeLLM:
        def invoke(self, messages):
            seen["prompt"] = messages[1][1]
            return SimpleNamespace(content='{"judgments": {'
                + ", ".join(f'"{k}": {{"verdict": "{"false" if k == "3" else "true"}", "confidence": 0.8,'
                            f' "reason": "r", "cited_chunk_ids": ["LAW#제766조"]}}' for k in "12345") + "}}")

    monkeypatch.setattr(solver_mod, "get_chat_model", lambda *a, **k: FakeLLM())
    rec = MCQSolver(settings, retriever=FakeRetriever()).solve(q1, RetrievalMode.C)
    assert rec["status"] == "ok" and rec["predicted"] == 3
    assert set(rec["retrieval"]) == set("12345")
    # 정답·허용 근거 표기 등 평가용 필드는 풀이 입력에 들어가지 않음
    assert "SENTINEL-EVIDENCE" not in seen["prompt"]
    assert "statement_labels" not in seen["prompt"] and '"answer"' not in seen["prompt"]


def test_parse_moj_2026_format():
    qs = import_exam(FIX / "synthetic_exam_moj.txt", None, "t", "t", "T").items
    assert [q.number for q in qs] == [1, 2]
    assert qs[0].form == "combination" and qs[0].polarity == "correct"
    assert "문 2. 라는 표현" in qs[0].items["ㄴ"]
    assert qs[1].polarity == "incorrect" and qs[1].options[5] == "마"


def test_ox_form_and_choice():
    from kant_rag.mcq.parse import parse_ox
    from kant_rag.mcq.schemas import ExamQuestion

    opts = {1: "ㄱ(○), ㄴ(○)", 2: "ㄱ(○), ㄴ(×)", 3: "ㄱ(×), ㄴ(○)", 4: "ㄱ(×), ㄴ(×)", 5: "ㄱ(○), ㄴ(○)"}
    q = ExamQuestion(id="X", number=1, stem="옳은 것(○)과 옳지 않은 것(×)을 올바르게 조합한 것은?",
                     items={"ㄱ": "a", "ㄴ": "b"}, options=opts)
    assert q.form == "ox" and parse_ox(opts[2]) == {"ㄱ": True, "ㄴ": False}
    assert choose_answer(q, {"ㄱ": J("true"), "ㄴ": J("false")})[0] == 2


def test_real_exam_file_parses_70():
    root = Path(__file__).parents[1]
    qs = import_exam(root / "data/exam/2026_civil.txt", None, "t", "t", "T").items
    assert [q.number for q in qs] == list(range(1, 71))
    assert {q.form for q in qs} == {"single", "combination", "ox"}
    assert all(len(q.options) == 5 for q in qs)


def test_rewrite_used_for_retrieval_with_fallback(settings, monkeypatch):
    q1 = exam().items[0]
    q1.evidence = [{"doc_id": "LAW", "chunk_id": "LAW#제766조", "location": "SENTINEL-EVIDENCE"}]
    s = settings.model_copy(deep=True)
    s.optimization.rewrite.enabled = True
    calls, queries = [], []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(messages[1][1])
            if len(calls) == 1:  # 리라이트: 3번 키 누락 → fallback
                return SimpleNamespace(content='{"1": "불법행위 손해배상 민법 제750조", "2": "정신적 손해 위자료",'
                                               ' "4": "제척기간", "5": "정기금 배상"}')
            return SimpleNamespace(content='{"judgments": {}}')

    class RecordingRetriever(FakeRetriever):
        def retrieve(self, query, mode):
            queries.append(query)
            return super().retrieve(query, mode)

    monkeypatch.setattr(solver_mod, "get_chat_model", lambda *a, **k: FakeLLM())
    rec = MCQSolver(s, retriever=RecordingRetriever()).solve(q1, RetrievalMode.C)
    assert queries[0] == "불법행위 손해배상 민법 제750조"
    assert rec["rewrite"]["fallback_keys"] == ["3"] and queries[2] == rec["rewrite"]["original"]["3"]
    assert "rewrite" in rec["timing_ms"] and "SENTINEL-EVIDENCE" not in calls[0]

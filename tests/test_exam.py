from civil_rag.exam.solver import (
    UNGROUNDED_WEIGHT,
    choice_expectation,
    choose_answer,
    count_choice_value,
    format_question,
    split_statements,
    stem_polarity,
    verdict_weight,
)


def V(verdict, grounded=True, conf=0.9):
    return {"verdict": verdict, "grounded": grounded, "confidence": conf}


def test_choose_answer_combination_picks_matching_set():
    choices = {1: "ㄱ, ㄴ", 2: "ㄱ, ㄷ", 3: "ㄴ, ㄹ", 4: "ㄷ, ㄹ", 5: "ㄱ, ㄹ"}
    verdicts = {"ㄱ": V("O"), "ㄴ": V("X"), "ㄷ": V("O"), "ㄹ": V("X")}
    pred, scores, mode = choose_answer("옳은 것을 모두 고른 것은?", choices, verdicts, "correct", ["ㄱ", "ㄴ", "ㄷ", "ㄹ"])
    assert (pred, mode) == (2, "combination")


def test_choose_answer_single_incorrect_and_ungrounded_weight():
    choices = {i: f"보기{i}" for i in range(1, 6)}
    verdicts = {"1": V("O"), "2": V("O"), "3": V("X", grounded=False, conf=0.9), "4": V("X", conf=0.6), "5": V("O")}
    pred, scores, _ = choose_answer("옳지 않은 것은?", choices, verdicts, "incorrect", None)
    assert pred == 4                                   # 근거 있는 X(0.6) > 근거 없는 X(0.9×0.5)
    assert abs(scores[3] - 0.9 * UNGROUNDED_WEIGHT) < 1e-9
    assert verdict_weight(V("O", grounded=False, conf=1.0)) == UNGROUNDED_WEIGHT


def test_choose_answer_count_type():
    choices = {1: "0개", 2: "1개", 3: "2개", 4: "3개", 5: "4개"}
    verdicts = {"ㄱ": V("O"), "ㄴ": V("X"), "ㄷ": V("O"), "ㄹ": V("O")}
    pred, _, mode = choose_answer("옳은 것은 몇 개인가?", choices, verdicts, "correct", ["ㄱ", "ㄴ", "ㄷ", "ㄹ"])
    assert (pred, mode) == (4, "count")
    assert count_choice_value("없음") == 0


def test_choose_answer_unknown_polarity_falls_back():
    pred, _, mode = choose_answer("甲이 청구할 수 있는 금액은?", {1: "1억 원"}, {}, "unknown", None)
    assert pred is None and mode.endswith("unknown_polarity")


def test_split_statements_joins_wrapped_lines():
    p = "ㄱ. 첫째 지문\n이어지는 줄\nㄴ. 둘째 지문"
    assert split_statements(p) == {"ㄱ": "첫째 지문 이어지는 줄", "ㄴ": "둘째 지문"}


def test_choice_expectation_patterns():
    letters = ["ㄱ", "ㄴ", "ㄷ", "ㄹ"]
    assert choice_expectation("ㄱ(○), ㄴ(×), ㄷ(○), ㄹ(×)", letters, "unknown") == {"ㄱ": "O", "ㄴ": "X", "ㄷ": "O", "ㄹ": "X"}
    assert choice_expectation("ㄱ, ㄷ", letters, "correct") == {"ㄱ": "O", "ㄴ": "X", "ㄷ": "O", "ㄹ": "X"}
    assert choice_expectation("ㄱ, ㄷ", letters, "incorrect") == {"ㄱ": "X", "ㄴ": "O", "ㄷ": "X", "ㄹ": "O"}
    assert choice_expectation("ㄱ, ㄷ", letters, "unknown") is None


def test_stem_polarity():
    assert stem_polarity("…에 관한 설명으로 옳지 않은 것은?") == "incorrect"
    assert stem_polarity("…에 관한 설명으로 틀린 것은?") == "incorrect"
    assert stem_polarity("…에 관한 설명으로 옳은 것은?") == "correct"
    assert stem_polarity("다음 중 甲이 청구할 수 있는 금액은?") == "unknown"


def test_format_question_orders_choices_and_marks():
    q = format_question({"stem": "옳은 것은?", "choices": {"2": "나", "1": "가", "3": "다", "4": "라", "5": "마"}})
    assert q.splitlines() == ["옳은 것은?", "① 가", "② 나", "③ 다", "④ 라", "⑤ 마"]


# ── statements 근거 표시·재검토 (2026 오답 분석 2차 수정) ──
from types import SimpleNamespace  # noqa: E402

from civil_rag.exam.solver import ExamSolver  # noqa: E402
from civil_rag.ingest.chunking import Chunk  # noqa: E402
from civil_rag.retrieval.types import Candidate  # noqa: E402


def _prec_solver(n_items=3, body_len=900):
    meta = {"doc_type": "prec", "court": "대법원", "decision_date": "2013-01-01", "case_no": "2012다1", "case_name": "부당이득"}
    chunks = {}
    for sec, part0 in (("판시사항", 0), ("판결요지", 0)):
        for i in range(n_items):
            cid = f"p1:{sec}:{i}"
            body = f"{sec}{i + 1} " + ("가" * body_len) + f" 결론{i + 1}"
            chunks[cid] = Chunk(cid, "p1", "prec", sec, f"[2012다1 | {sec} [{i + 1}]]\n{body}",
                                {**meta, "section": sec, "item": f"[{i + 1}]", "part": i})
    solver = ExamSolver(retriever=SimpleNamespace(chunks=chunks))
    return solver, chunks, meta


def test_doc_text_puts_retrieved_item_first_and_keeps_its_conclusion():
    solver, chunks, meta = _prec_solver()
    c = chunks["p1:판결요지:2"]
    cand = Candidate(c.chunk_id, c.doc_id, c.section, c.text, {**c.metadata})
    text = solver._doc_text(cand)
    first_item = text.split("\n")[1]
    assert first_item.startswith("[3] (검색된 항목)")
    assert "결론3" in text                       # 검색된 [3] 의 결론은 잘리지 않음
    assert "판시사항3" in text                    # 같은 항목의 판시사항도 함께


def test_merge_docs_interleaves_and_collects_focus():
    solver = ExamSolver(retriever=SimpleNamespace(chunks={}))

    def C(cid, doc):
        return Candidate(cid, doc, "판결요지", "", {"doc_type": "prec"})

    a = [C("a:1", "A"), C("b:1", "B"), C("a:2", "A"), C("c:1", "C")]
    b = [C("d:1", "D"), C("a:3", "A")]
    focus: dict = {}
    out = solver._merge_docs([a, b], 3, focus)
    assert [x.doc_id for x in out] == ["A", "D", "B"]
    assert focus["A"] == {"a:1", "a:2", "a:3"}
    more = solver._merge_docs([[C("e:1", "E"), C("a:9", "A")]], 1, focus, base=out)
    assert [x.doc_id for x in more] == ["A", "D", "B", "E"]


def test_decisive_keys_are_statements_separating_top_two():
    choices = {1: "ㄱ, ㄴ", 2: "ㄱ, ㄷ", 3: "ㄴ, ㄷ"}
    scores = {1: 2.0, 2: 1.5, 3: -1.0}
    keys = ExamSolver._decisive_keys(choices, scores, ["ㄱ", "ㄴ", "ㄷ"], "correct", "옳은 것을 모두 고른 것은?")
    assert keys == ["ㄴ", "ㄷ"]
    assert ExamSolver._decisive_keys({1: "a", 2: "b"}, {1: 1.0, 2: 0.5}, None, "incorrect", "옳지 않은 것은?") == ["1", "2"]


def test_ensure_law_lifts_lower_ranked_article():
    solver = ExamSolver(retriever=SimpleNamespace(chunks={}))
    prec = [Candidate(f"p{i}:판결요지:0", f"p{i}", "판결요지", "", {"doc_type": "prec"}) for i in range(3)]
    law = Candidate("law:민법:191-0", "law:민법", "제191조", "", {"doc_type": "law"})
    focus: dict = {}
    docs, status = solver._ensure_law(prec[:2], [prec + [law]], "q", "C", focus)
    assert status == "lifted" and docs[-1] is law and "law:민법:191-0" in focus
    docs2, status2 = solver._ensure_law(docs, [prec], "q", "C", focus)
    assert status2 == "had" and docs2 == docs


def test_overruled_cases_in_sentence():
    from civil_rag.ingest.overruled import overruled_cases_in

    body = ("…따라서 원심은 정당하다. 이와 달리 대법원 1991. 5. 28. 선고 91다6658 판결, 대법원 1988. 9. 27. "
            "선고 87다카279 판결 등은 이 판결의 견해에 배치되는 범위 내에서 이를 변경하기로 한다. 그러므로 상고를 기각한다.")
    assert overruled_cases_in(body, {"2002다9660"}) == ["91다6658", "87다카279"]
    assert overruled_cases_in("변경하기로 하는 약정을 하였다.", set()) == []


def test_fuse_docs_rrf_prefers_docs_found_by_several_queries():
    solver = ExamSolver(retriever=SimpleNamespace(chunks={}))

    def C(cid, doc):
        return Candidate(cid, doc, "판결요지", "", {"doc_type": "prec"})

    a = [C("a:1", "A"), C("b:1", "B"), C("c:1", "C")]
    b = [C("b:2", "B"), C("d:1", "D")]
    c = [C("b:3", "B"), C("a:2", "A")]
    focus: dict = {}
    fused = solver._fuse_docs([a, b, c], focus)
    assert [x.doc_id for x in fused][:2] == ["B", "A"]
    assert focus["B"] == {"b:1", "b:2", "b:3"}


def test_vote_majority_and_agreement_confidence(monkeypatch):
    solver = ExamSolver(retriever=SimpleNamespace(chunks={}))
    answers = iter([
        {"ㄱ": {"verdict": "O", "grounded": True, "confidence": 0.9, "reason": "a", "cited": ["x"]}},
        {"ㄱ": {"verdict": "X", "grounded": False, "confidence": 0.6, "reason": "b", "cited": []}},
        {"ㄱ": {"verdict": "O", "grounded": True, "confidence": 0.7, "reason": "c", "cited": ["y"]}},
    ])
    lock = __import__("threading").Lock()

    def fake_judge(*_a, **_k):
        with lock:
            return next(answers), []

    monkeypatch.setattr(solver, "_judge", fake_judge)
    out, _ = solver._vote({}, {"ㄱ": "t"}, {}, {"ㄱ": "ㄱ."}, {}, [])
    v = out["ㄱ"]
    assert v["verdict"] == "O" and v["grounded"] and v["votes"] == "2O/1X"
    assert abs(v["confidence"] - 0.8 * 2 / 3) < 1e-3
    assert v["cited"] == ["x", "y"]


def test_stem_topic_puts_question_first_and_drops_labels():
    from civil_rag.exam.solver import stem_topic

    stem = ("[사안의 경위] 부동산 개발 및 임대업을 영위하는 당사자들 사이에 다양한 손해배상 분쟁이 발생하였다. "
            "손해배상의 범위에 관한 설명 중 옳지 않은 것을 모두 고른 것은? (다툼이 있는 경우 판례에 의함)")
    t = stem_topic(stem)
    assert t.startswith("손해배상의 범위에 관한 설명 중 옳지 않은 것을 모두 고른 것은?")
    assert "[사안의 경위]" not in t and "다툼이 있는" not in t and len(t) <= 150
    assert stem_topic("전세권에 관한 설명 중 옳지 않은 것은?") == "전세권에 관한 설명 중 옳지 않은 것은?"
    assert stem_topic("물음표 없는 발문") == "물음표 없는 발문"


def test_solve_statements_flow_offline(monkeypatch):
    """LLM·DB 없이 statements 전략 전체 흐름(검색 계획 → 검색 합치기 → 다수결 판단 → 재검토 → 번호)이 돈다."""
    from civil_rag.exam import solver as S

    chunks = {}
    for doc in ("p1", "p2", "p3"):
        cid = f"{doc}:판결요지:0"
        chunks[cid] = Chunk(cid, doc, "prec", "판결요지", f"[{doc} | 판결요지 [1]]\n본문 {doc}",
                            {"doc_type": "prec", "case_no": doc, "item": "[1]", "part": 0, "section": "판결요지"})
    chunks["law:민법:507"] = Chunk("law:민법:507", "law:민법", "law", "제507조", "[민법 제507조]\n혼동",
                                   {"doc_type": "law", "law_name": "민법", "article": "제507조"})
    solver = ExamSolver(retriever=SimpleNamespace(chunks=chunks, _candidate=lambda cid: Candidate(
        cid, chunks[cid].doc_id, chunks[cid].section, chunks[cid].text, dict(chunks[cid].metadata))))

    def fake_rc(q, run_config, doc_type=None, light=False):
        ids = ["law:민법:507"] if doc_type == "law" else ["p1:판결요지:0", "p2:판결요지:0", "p3:판결요지:0"]
        return [solver.retriever._candidate(i) for i in ids], {"query": q, "rewrite_status": None}

    plan = S.IssuePlan(queries=[
        S.IssueQuery(key="ㄱ", plain="", issue="혼동", exception="", articles=["민법 제507조"]),
        S.IssueQuery(key="ㄴ", plain="할 수 있다", issue="대리", exception="표현대리", articles=[]),
    ])
    calls = {"n": 0}

    def fake_judge(item, targets, per_key, labels, focus, shared=None, notes=None, excerpts=None):
        calls["n"] += 1
        assert notes == {"ㄴ": "할 수 있다"}
        v = {k: {"verdict": "O" if k == "ㄱ" else "X", "grounded": k == "ㄱ", "confidence": 0.9,
                 "reason": "r", "cited": []} for k in targets}
        return v, [c for k in targets for c in per_key.get(k, [])]

    monkeypatch.setattr(solver, "_ranked_candidates", fake_rc)
    monkeypatch.setattr(solver, "_plan_queries", lambda item, t, l: ({q.key: q for q in plan.queries}, "ok"))
    monkeypatch.setattr(solver, "_judge", fake_judge)
    monkeypatch.setattr(solver, "_doc_index", lambda: {})
    item = {"no": 1, "stem": "[사안] 배경. 대리에 관한 설명 중 옳은 것을 모두 고른 것은?",
            "passage": "ㄱ. 첫 지문\nㄴ. 할 수 없지 않다",
            "choices": {"1": "ㄱ", "2": "ㄴ", "3": "ㄱ, ㄴ", "4": "없음", "5": "ㄴ, ㄱ"}, "answer": 1}
    r = solver._solve_statements(item, "C", "correct")
    assert r["predicted"] == 1
    assert r["queries"]["ㄱ"]["law_quota"] == "named"           # 계획이 짚은 조문 원문을 바로 붙임
    assert r["queries"]["plan"]["topic"].startswith("대리에 관한 설명")
    assert "ㄴ:plain" in r["queries"]
    assert calls["n"] == S.FIRST_VOTES + S.VOTES                 # 첫 판단 다수결 + 재검토 다수결


def test_junyong_targets_same_law_only():
    from civil_rag.exam.solver import junyong_targets

    text = ("[민법 제290조]\n제290조(준용규정) ① 제213조, 제214조, 제216조 내지 제244조의 규정은 지상권자간 또는 "
            "지상권자와 인지소유자간에 이를 준용한다. ② 다른 문장이다. ③ 「상법」 제48조를 준용한다.")
    keys = junyong_targets(text, "민법", "law:민법:290")
    assert keys[:3] == ["law:민법:213", "law:민법:214", "law:민법:216"]
    assert "law:민법:290" not in keys and not any("상법" in k for k in keys)


def test_best_paragraphs_picks_overlapping_reason_paragraph():
    from civil_rag.exam.solver import best_paragraphs

    body = ("【원고】 갑<br/>【이    유】 상고이유를 판단한다.<br/>  가. 양도담보권자는 목적물의 교환가치를 취득하는 것을 목적으로 "
            "하므로 부합으로 인한 실질적 이익은 양도담보권설정자에게 귀속되어 보상청구는 설정자를 상대로 하여야 한다.<br/>"
            "  나. 소송비용에 관한 부분은 이유 없다. 원심의 판단에 잘못이 없다고 본다.<br/>")
    out = best_paragraphs(body, "부합으로 인한 이익은 양도담보권설정자에게 귀속하므로 보상청구 상대방은 설정자")
    assert "양도담보권설정자에게 귀속" in out and "소송비용" not in out
    assert best_paragraphs("", "질의") == ""


def test_fill_blank_plan_and_choose():
    from civil_rag.exam.solver import choose_fill, fill_blank_plan

    item = {"stem": "괄호 안에 들어갈 말을 올바르게 나열한 것은?",
            "passage": "ㄱ. 전부명령을 받는 것은 ( A ).\nㄴ. 피보전채권이 될 수 ( B ).\nA B",
            "choices": {"1": "허용되지 않는다 / 있다", "2": "허용된다 / 없다", "3": "허용된다 / 있다"}}
    targets, labels, keys = fill_blank_plan(item)
    assert targets["A2"] == "전부명령을 받는 것은 허용된다."
    assert targets["B1"] == "피보전채권이 될 수 있다."          # 머리줄 'A B' 는 떼어냄
    assert keys == {1: ["A1", "B1"], 2: ["A2", "B2"], 3: ["A2", "B1"]}
    V = lambda v: {"verdict": v, "grounded": True, "confidence": 0.9}
    pred, _, mode = choose_fill(keys, {"A1": V("X"), "A2": V("O"), "B1": V("O"), "B2": V("X")})
    assert (pred, mode) == (3, "fill")
    assert fill_blank_plan({"stem": "?", "passage": "ㄱ. 보통 지문", "choices": {"1": "ㄱ"}}) is None


def test_vote_escalates_split_decisive_statement(monkeypatch):
    from civil_rag.exam import solver as S

    solver = ExamSolver(retriever=SimpleNamespace(chunks={}))
    seq = iter(["O", "X", "O", "X", "X"])          # 3표 2:1 → 결정적 지문이라 2표 더 → 2:3 으로 X
    lock = __import__("threading").Lock()
    calls = []

    def fake_judge(item, targets, *a, **k):
        with lock:
            calls.append(sorted(targets))
            return {"ㄴ": {"verdict": next(seq), "grounded": True, "confidence": 0.8, "reason": "", "cited": []}}, []

    monkeypatch.setattr(solver, "_judge", fake_judge)
    out, _ = solver._vote({}, {"ㄴ": "t"}, {}, {"ㄴ": "ㄴ."}, {}, [], escalate={"ㄴ"})
    assert len(calls) == S.VOTES + S.EXTRA_VOTES
    assert out["ㄴ"]["votes"] == "2O/3X" and out["ㄴ"]["verdict"] == "X"
    calls.clear()
    seq = iter(["O", "X", "O"])
    out, _ = solver._vote({}, {"ㄴ": "t"}, {}, {"ㄴ": "ㄴ."}, {}, [])   # 결정적이 아니면 추가 없음
    assert len(calls) == S.VOTES and out["ㄴ"]["verdict"] == "O"

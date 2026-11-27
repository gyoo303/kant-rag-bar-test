"""v6: 연결 지도·역방향 준용·조각 합치기·조문 위치/제목·다시 찾는 검색·개수형 동점·다수결·복수 정답 (가짜 검색기·가짜 LLM)."""
import json

import pytest

from kant_rag.config import get_settings
from kant_rag.mcq.context import (
    ChunkGraph,
    build_title_index,
    chapter_company,
    company_type,
    title_matches,
)
from kant_rag.mcq.defense import quote_supported
from kant_rag.mcq.io import parse_answer_cell
from kant_rag.mcq.links import LinkGraph, parse_ref_articles, parse_ref_cases
from kant_rag.mcq.presets import PRESETS, apply_overrides
from kant_rag.mcq.prompts import MCQ_RESEARCH_USER, MCQ_SYSTEM_V6
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.mcq.solver import MCQSolver, _norm_key, _type_balance, build_context
from kant_rag.retrieval.pipeline import RetrievalMode
from kant_rag.schemas import Chunk, RetrievedChunk


def _law(art, title, body, section, doc="LAW-COMM", law="상법"):
    return Chunk(chunk_id=f"{doc}#{art}", doc_id=doc, title=law, text=f"[{law}] {art}({title})\n{body}",
                 section=f"{section} > {art}({title})", line_start=1, line_end=1,
                 metadata={"doc_type": "statute", "article": art, "article_title": title})


def _case(no, item, text, decided, part=None, parts=None):
    cid = f"CASE#{no}#{item}" + (f"~{part}" if part else "")
    head = f"[판례] 대법원 {decided} {no} 판결요지 [{item}]" + (f" ({part}/{parts})" if part else "")
    return Chunk(chunk_id=cid, doc_id="CASES-SC", title=f"대법원 {no}", text=f"{head}\n{text}", section="s",
                 line_start=1, line_end=1, metadata={"doc_type": "case", "case_no": no, "decided": decided})


def _corpus():
    xs = [
        _law("제208조", "공동대표", "②전항의 경우에도 제3자의 회사에 대한 의사표시는 공동대표의 권한있는 사원 1인에 대하여 이를 함으로써 그 효력이 생긴다.",
             "제3편 회사 > 제2장 합명회사"),
        _law("제389조", "대표이사", "②전항의 경우에는 수인의 대표이사가 공동으로 회사를 대표할 것을 정할 수 있다.\n③제208조제2항, 제209조, 제210조와 제386조의 규정은 대표이사에 준용한다.",
             "제3편 회사 > 제4장 주식회사 > 제3절 회사의 기관"),
        _law("제481조", "변제자대위", "변제할 정당한 이익이 있는 자는 변제로 당연히 채권자를 대위한다.", "제3편 채권 > 제1장 총칙",
             doc="LAW-CIVIL", law="민법"),
        _case("99다23888", "1", "추심명령이 있으면 채무자는 피압류채권에 대한 이행소송의 당사자적격을 상실한다.", "20000411"),
        _case("2021다252977", "1", "채무자는 추심명령이 있더라도 당사자적격을 상실하지 아니한다.", "20251023"),
        _case("2014다51756", "1", "변제자대위 첫 조각 법정대위자는", "20150101", 1, 2),
        _case("2014다51756", "1", "채권자를 대위한다는 결론 조각.", "20150101", 2, 2),
    ]
    return {c.chunk_id: c for c in xs}


def _raw_cases(tmp_path):
    d = tmp_path / "raw" / "cases"
    d.mkdir(parents=True)
    rows = [
        {"case_no": "2021다252977", "decided": "20251023",
         "ref_cases": "[1] 대법원 2000. 4. 11. 선고 99다23888 판결(공2000상, 1)(변경), 대법원 2009. 11. 12. 선고 2009다48879 판결(변경)",
         "ref_articles": "[1] 민사집행법 제229조"},
        {"case_no": "2014다51756", "decided": "20150101", "ref_cases": "", "ref_articles": "민법 제368조, 제481조, 제482조"},
    ]
    (d / "cases_x.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return d


# ---------- 원자료 파싱 ----------
def test_parse_refs():
    r = parse_ref_cases("[1][2] 대법원 1998. 4. 23. 선고 95다36466 전원합의체 판결(공1998상, 1338) / "
                        "[2] 대법원 1968. 9. 24. 선고 68다1516 판결(집16-3, 민61)(변경)")
    assert r == [(["1", "2"], "95다36466", "19980423", False), (["2"], "68다1516", "19680924", True)]
    a = parse_ref_articles("[1] 민법 제105조 / [2] 민법 제430조, 채무자 회생 및 파산에 관한 법률 제250조 제2항, "
                           "같은 법 제37조의3, 구 민법(2011. 3. 7. 법률 제10429호로 개정되기 전의 것) 제5조")
    assert (["2"], "채무자 회생 및 파산에 관한 법률", "제37조의3") in a and (["2"], "민법", "제5조") in a


def test_link_graph(tmp_path):
    by_id = _corpus()
    lg = LinkGraph(by_id, _raw_cases(tmp_path), cache=tmp_path / "links.pkl")
    assert lg.overruled_info("99다23888") == {"overruled_by": [("2021다252977", "20251023")]}
    assert ("CASE#2021다252977#1", "overruler") in lg.candidates(["CASE#99다23888#1"])
    assert lg.candidates(["CASE#99다23888#1"], cutoff="20230101") == []  # 기준 시점 뒤의 변경 판례는 연결 안 함
    assert lg.candidates(["LAW-CIVIL#제481조"]) == [("CASE#2014다51756#1~1", "article_case")]
    assert (tmp_path / "links.pkl").exists()
    assert LinkGraph(by_id, tmp_path / "none", cache=tmp_path / "links.pkl").overruled_by == {}


# ---------- 역방향 준용·조각·조문 위치·제목 ----------
def test_reverse_usage_and_pieces():
    g = ChunkGraph(_corpus())
    assert g.statute_users(["LAW-COMM#제208조"]) == ["LAW-COMM#제389조"]
    assert g.expand_references(["LAW-COMM#제208조"]) == []  # 기존 A4 동작은 그대로 (적용 대상일 때만 역방향)
    assert g.item_pieces("CASE#2014다51756#1~2") == ["CASE#2014다51756#1~1", "CASE#2014다51756#1~2"]
    t = g.item_text("CASE#2014다51756#1~2")
    assert t.startswith("[판례] 대법원 20150101 2014다51756 판결요지 [1]\n") and "결론 조각" in t and "(1/2)" not in t


def test_chapter_and_title():
    by_id = _corpus()
    assert company_type("공동대표이사 중 1인에 대한 의사표시") == "주식회사"
    assert company_type("합명회사의 사원") == "합명회사" and company_type("주식회사와 합명회사") is None
    assert chapter_company(by_id["LAW-COMM#제208조"]) == "합명회사"
    idx = build_title_index(by_id)
    assert set(title_matches("공동대표이사 1인에 대한 의사표시", idx)) == {"LAW-COMM#제208조", "LAW-COMM#제389조"}


def test_build_context_merge_and_links():
    by_id = _corpus()
    g = ChunkGraph(by_id)
    c = apply_overrides(get_settings(), PRESETS["v6"]).mcq
    r = RetrievedChunk(chunk=by_id["CASE#2014다51756#1~2"], score=1.0, rank=1, source="rerank")
    ev, used, info = build_context({"ㄱ": [r]}, c, g, None, links=[("LAW-COMM#제389조", "chapter_user")],
                                   annotate=lambda ch: ' chapter="x"' if ch.metadata["doc_type"] == "statute" else "")
    assert used[:2] == ["CASE#2014다51756#1~1", "CASE#2014다51756#1~2"] and "LAW-COMM#제389조" in used
    assert ev.count("<doc ") >= 2 and 'kind="link" chapter="x"' in ev and info["links"] == ["LAW-COMM#제389조"]


# ---------- 작은 규칙들 ----------
def test_small_rules():
    assert parse_answer_cell("4|5") == (4, [4, 5]) and parse_answer_cell("3") == (3, [])
    q = ExamQuestion(id="X", number=13, stem="옳은 것은?", options={i: str(i) for i in range(1, 6)}, answer=5, accepted=[5, 4])
    assert q.is_correct(4) and q.is_correct(5) and not q.is_correct(3) and not q.is_correct(None)
    assert [_norm_key(x, ["1", "ㄱ"]) for x in ["①", "보기 1", "ㄱ."]] == ["1", "1", "ㄱ"]
    assert quote_supported("당사자적격을 상실한다…이행소송", ["추심명령이 있으면 채무자는 피압류채권에 대한 이행소송의 당사자적격을 상실한다."],
                           mode="relaxed")
    assert "{new_evidence}" in MCQ_RESEARCH_USER and '"missing"' in MCQ_SYSTEM_V6 and "chapter=" in MCQ_SYSTEM_V6
    by_id = _corpus()
    rs = [RetrievedChunk(chunk=by_id[x], score=1.0 - i / 10, rank=i + 1, source="rerank")
          for i, x in enumerate(["CASE#99다23888#1", "CASE#2021다252977#1", "LAW-COMM#제389조"])]
    out, moved = _type_balance({"ㄱ": rs}, 2)
    assert [r.chunk.chunk_id for r in out["ㄱ"]][:2] == ["CASE#99다23888#1", "LAW-COMM#제389조"] and moved == {"ㄱ": "LAW-COMM#제389조"}


# ---------- 통합: 개수형 문 40 유형 (조문 못 찾아 유보 → 연결·2차 검색으로 해결) ----------
class _FakeVector:
    def __init__(self, by_id):
        self.chunks_by_id = by_id


class _FakeReranker:
    def rerank(self, query, cands, top_k):
        return [c.model_copy(update={"score": 0.9 - i * 0.01, "rank": i + 1}) for i, c in enumerate(cands)][:top_k]


class _FakeRetriever:
    def __init__(self, by_id):
        self.vector = _FakeVector(by_id)
        self.reranker = _FakeReranker()
        self.calls = []

    def retrieve(self, query, mode, date_to=None):
        self.calls.append(query)
        ids = ["LAW-COMM#제208조", "CASE#99다23888#1", "LAW-CIVIL#제481조"]
        if "준용" in query:  # 2차 검색(missing)
            ids = ["LAW-COMM#제389조", "LAW-COMM#제208조"]
        by = self.vector.chunks_by_id
        return {"final": [RetrievedChunk(chunk=by[x], score=1.0 - i * 0.1, rank=i + 1, source="rerank") for i, x in enumerate(ids)]}


def _make_llm(log):
    def fake(*args, **kwargs):
        system, user = args[2][0][1], args[2][1][1]
        log.append(user)
        if "검색용 질의" in system:
            return json.dumps({"①": {"issue": "ㄱ 쟁점"}, "ㄴ": {"issue": "ㄴ 쟁점"}}, ensure_ascii=False), [{}]
        if "<new_evidence>" in user:  # 2차 판단
            return json.dumps({"judgments": {"ㄴ": {
                "verdict": "true", "confidence": 0.95, "reason": "제389조③이 제208조②를 준용",
                "quote": "제208조제2항…규정은 대표이사에 준용한다", "cited_chunk_ids": ["LAW-COMM#제389조"]}}},
                ensure_ascii=False), [{}]
        return json.dumps({"judgments": {
            "ㄱ": {"verdict": "true", "confidence": 1.0, "reason": "조문", "quote": "변제로 당연히 채권자를 대위한다",
                  "cited_chunk_ids": ["LAW-CIVIL#제481조"]},
            "ㄴ": {"verdict": "unknown", "confidence": 0.3, "reason": "주식회사 조문 없음", "quote": "",
                  "missing": "상법 대표이사 공동대표 의사표시 준용", "cited_chunk_ids": []}}}, ensure_ascii=False), [{}]
    return fake


@pytest.mark.parametrize("preset", ["v5", "v6", "v6r"])
def test_solve_v6_research(monkeypatch, tmp_path, preset):
    log = []
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", _make_llm(log))
    raw = _raw_cases(tmp_path)
    s = apply_overrides(get_settings(), {**PRESETS[preset], "paths.raw_dir": str(raw.parent),
                                         "paths.index_dir": str(tmp_path / "index")})
    r = _FakeRetriever(_corpus())
    solver = MCQSolver(s, retriever=r)
    q = ExamQuestion(id="E", number=40, stem="상법에 관한 설명 중 옳은 것은 몇 개인가?",
                     items={"ㄱ": "변제할 정당한 이익이 있는 자는 변제로 당연히 채권자를 대위한다.",
                            "ㄴ": "공동대표이사 중 1인에 대한 제3자의 의사표시는 회사에 대하여 효력이 있다."},
                     options={1: "0개", 2: "1개", 3: "2개", 4: "3개", 5: "4개"}, answer=3)
    rec = solver.solve(q, RetrievalMode.C, "t")
    if preset == "v5":
        assert "research" not in rec and "links" not in rec and rec["predicted"] == 2  # 기대 개수 1.5 → 작은 번호
        return
    assert rec["rewrite"]["fallback_keys"] == ["ㄱ"]  # "①" 은 ㄱ 이 아니므로 정규화해도 fallback, ㄴ 은 그대로
    ch = rec["links"]["chosen"]
    assert ch.get("LAW-COMM#제389조") == "chapter_user"  # M1: 합명회사 장 조문 → 주식회사 장 준용 조문
    assert "CASE#2021다252977#1" in ch  # 2-1 변경한 판례
    first = log[1]
    assert 'overruled_by="2021다252977(2025-10-23)"' in first and 'chapter="제3편 회사 > 제2장 합명회사"' in first
    assert "변제자대위 첫 조각 법정대위자는\n채권자를 대위한다는" in first or "CASE#2014다51756" not in first
    res = rec["research"]
    assert res["keys"][0] == "ㄴ" and res["reasons"]["ㄴ"] == "유보"
    assert res["queries"]["ㄴ"] == ["상법 대표이사 공동대표 의사표시 준용"]
    assert res["changed"]["ㄴ"]["to"] == ["true", 0.95] and res["changed"]["ㄴ"]["quote_ok"] is True
    assert rec["predicted"] == 3 and rec["judgments"]["ㄴ"]["verdict"] == "true"


def test_count_tie_and_vote(monkeypatch):
    s = apply_overrides(get_settings(), {**PRESETS["v6r"], "mcq.research": False})
    solver = MCQSolver(s, retriever=_FakeRetriever(_corpus()))
    answers = iter(["true", "true", "false"])

    def fake(*args, **kwargs):
        return json.dumps({"judgments": {"ㄴ": {"verdict": next(answers), "confidence": 0.9, "reason": "r"}}}), [{}]
    monkeypatch.setattr("kant_rag.mcq.solver.call_llm", fake)
    q = ExamQuestion(id="E", number=40, stem="옳은 것은 몇 개인가?", items={"ㄱ": "a", "ㄴ": "b"},
                     options={1: "0개", 2: "1개", 3: "2개", 4: "3개", 5: "4개"})
    t = StatementJudgment(verdict="true", confidence=1.0, reason="")
    u = StatementJudgment(verdict="unknown", confidence=0.0, reason="")
    rec = {"judgments": {"ㄱ": t.model_dump(), "ㄴ": u.model_dump()}, "status": "ok", "timing_ms": {},
           "option_scores": {1: -1.5, 2: -0.5, 3: -0.5, 4: -1.5, 5: -2.5}, "predicted": 2}
    rec = solver._tiebreak(q, rec, 0.0, "sys", "ev", [])
    assert rec["tiebreak"]["count_tie"] and rec["tiebreak"]["keys"] == ["ㄴ"]
    assert rec["votes"]["tiebreak"]["ㄴ"] == ["true", "true", "false"]
    assert rec["judgments"]["ㄴ"]["confidence"] == pytest.approx(0.6) and rec["predicted"] == 3

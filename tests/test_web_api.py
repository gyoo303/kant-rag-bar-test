"""웹 API: 엔진 출력 → 화면용 JSON 변환과 상태 구분 (실제 색인·LLM 없이 가짜 엔진으로)."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from kant_rag.config import get_settings
from kant_rag.schemas import Chunk
from kant_rag.web import api

SAMPLE = """무권대리에 관한 설명 중 옳은 것을 모두 고른 것은? (다툼이 있는 경우 판례에 의함)
ㄱ. 본인이 추인하지 아니하면 본인에 대하여 효력이 없다.
ㄴ. 상대방이 대리권 없음을 알았더라도 추인 전이면 계약을 철회할 수 있다.
① ㄱ
② ㄴ
③ ㄱ, ㄴ
④ ㄴ
⑤ ㄱ, ㄴ
"""

CHUNKS = {
    "LAW-CIVIL#제130조": Chunk(chunk_id="LAW-CIVIL#제130조", doc_id="LAW-CIVIL", title="민법",
                             text="[민법] 제130조(무권대리) 본인이 이를 추인하지 아니하면 본인에 대하여 효력이 없다.",
                             metadata={"doc_type": "statute", "article": "제130조", "source": "law.go.kr"}),
    "CASE#2017다213838#1": Chunk(chunk_id="CASE#2017다213838#1", doc_id="CASE-2017다213838", title="대법원 2017다213838",
                                text="상대방이 대리권이 없음을 알았다는 점에 대한 증명책임은 본인에게 있다.",
                                metadata={"doc_type": "case", "case_no": "2017다213838", "decided": "20170629",
                                          "prec_id": "123", "source": "law.go.kr 판례 API"}),
}


class FakeAgent:
    def __init__(self, rec):
        self.rec = rec

    def ask(self, question, mode=None):
        return self.rec


class FakeSolver:
    def solve(self, q, mode=None):
        return {"status": "ok", "predicted": 1, "option_scores": {1: 1.0, 2: 0.0},
                "models": {"llm_model": "gpt-test"},
                "judgments": {"ㄱ": {"verdict": "true", "confidence": 0.99, "reason": "제130조",
                                    "cited_chunk_ids": ["LAW-CIVIL#제130조"], "quote": "본인에 대하여 효력이 없다"},
                              "ㄴ": {"verdict": "unknown", "confidence": 0.4, "reason": "근거 없음",
                                    "cited_chunk_ids": []}},
                "quote_check": {"ㄱ": True}}


class FakeEngine:
    def __init__(self, qa_rec=None, raise_on=None):
        self.base = get_settings()
        self.lock = threading.Lock()
        self.qa_rec = qa_rec
        self.raise_on = raise_on
        self.graph = None

    def ask(self, model, question, mode):
        if self.raise_on == "ask":
            raise TimeoutError("request timed out key=sk-abcdefghijkl")
        return FakeAgent(self.qa_rec).ask(question)

    def solver(self, model, preset):
        return FakeSolver()

    def chunk(self, cid):
        return CHUNKS.get(cid)


@pytest.fixture
def client(monkeypatch):
    def make(**kw):
        monkeypatch.setattr(api, "ENGINE", FakeEngine(**kw))
        return TestClient(api.app)
    return make


def test_config_lists_default_model(client, monkeypatch):
    monkeypatch.delenv("WEB_MODEL_OPTIONS", raising=False)
    r = client().get("/api/config").json()
    assert r["models"][0]["default"] is True
    assert any(m["id"] == "hybrid_rerank" for m in r["modes"])


def test_model_options_skip_provider_without_key(monkeypatch):
    monkeypatch.setenv("WEB_MODEL_OPTIONS", "anthropic:claude-x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert [m["id"] for m in api.model_options(get_settings())][1:] == []


def test_detects_exam_and_normalizes_mcq(client):
    r = client().post("/api/chat", json={"text": SAMPLE}).json()
    assert r["type"] == "mcq_batch" and r["status_kind"] == "ok"
    item = r["items"][0]
    assert item["predicted_label"] == "①"
    st = {s["key"]: s for s in item["statements"]}
    assert st["ㄱ"]["verdict"] == "O" and st["ㄱ"]["quote_verified"] is True
    assert st["ㄴ"]["verdict"] == "?" and st["ㄴ"]["quote_verified"] is None  # 대조 안 했으면 검증 표시 없음
    doc = item["docs"]["LAW-CIVIL#제130조"]
    assert doc["kind"] == "statute" and doc["article"] == "제130조" and "url" in doc


def test_qa_insufficient_is_not_error(client):
    rec = {"answer": {"status": "insufficient_evidence", "answer": "정보 부족", "citations": []}}
    r = client(qa_rec=rec).post("/api/chat", json={"text": "질문"}).json()
    assert r["type"] == "qa" and r["status_kind"] == "insufficient" and r["error"] is None


def test_qa_citations_carry_real_case_metadata(client):
    rec = {"answer": {"status": "ok", "answer": "본인이 증명", "citations": [
        {"chunk_id": "CASE#2017다213838#1", "doc_id": "x", "title": "t", "location": "l", "quote": "q"},
        {"chunk_id": "CASE#없는판례#1", "doc_id": "x", "title": "t", "location": "l", "quote": "q"}]}}
    r = client(qa_rec=rec).post("/api/chat", json={"text": "증명책임?"}).json()
    assert r["citations"] == ["CASE#2017다213838#1"]  # 색인에 없는 청크는 표시하지 않음
    d = r["docs"]["CASE#2017다213838#1"]
    assert d["case_no"] == "2017다213838" and d["decided"] == "2017. 6. 29."


def test_system_error_is_separate_and_masks_keys(client):
    r = client(raise_on="ask").post("/api/chat", json={"text": "질문"}).json()
    assert r["type"] == "error" and r["status_kind"] == "error"
    assert "sk-abcdef" not in r["error"]


def test_missing_index_returns_setup_error(client, monkeypatch):
    """엔진이 색인 없음으로 SystemExit 를 보내도 서버는 죽지 않고 안내를 돌려준다."""
    eng = FakeEngine()

    def no_index(model, question, mode):
        raise SystemExit("색인이 없거나 미완성입니다 (없음: chunks.jsonl).\n→ `uv run kant-rag build-index` 를 끝까지 실행한 뒤 다시 시도하세요.")
    eng.ask = no_index
    monkeypatch.setattr(api, "ENGINE", eng)
    r = TestClient(api.app).post("/api/chat", json={"text": "질문"}).json()
    assert r["type"] == "error" and r["code"] == "setup" and "build-index" in r["error"]


def test_direct_refs_find_cited_article_and_case():
    arts = {("민법", "제134조"): ["LAW-CIVIL#제134조"], ("민사소송법", "제134조"): ["LAW-CIVPRO#제134조"],
            ("상법", "제382조의3"): ["LAW-COMM#제382조의3"]}
    cases = {"2013다213038": ["CASE#2013다213038#1"]}
    assert api.direct_refs("민법 제134조 내용 알려줘", arts, cases) == ["LAW-CIVIL#제134조"]
    assert api.direct_refs("제134조는?", arts, cases) == ["LAW-CIVIL#제134조"]  # 법령명 없으면 민법
    assert api.direct_refs("상법 제382조의 3 내용", arts, cases) == ["LAW-COMM#제382조의3"]
    assert api.direct_refs("2013다213038 판례 요지", arts, cases) == ["CASE#2013다213038#1"]
    assert api.direct_refs("해제와 해지의 차이", arts, cases) == []


def test_partial_answer_kept_with_citations(monkeypatch):
    rec = {"answer": {"status": "insufficient_evidence", "answer": "확인되는 범위에서는 …", "citations": [
        {"chunk_id": "LAW-CIVIL#제130조", "doc_id": "x", "title": "t", "location": "l", "quote": "q"}]}}
    monkeypatch.setattr(api, "ENGINE", FakeEngine())
    r = api.normalize_qa(rec)
    assert r["status_kind"] == "partial" and r["citations"] == ["LAW-CIVIL#제130조"]
    r2 = api.normalize_qa({"answer": {"status": "insufficient_evidence",
                                  "answer": "제공된 문서에서 이 질문에 답할 근거를 찾지 못했습니다. 담당 부서에 확인해 주세요.", "citations": []}})
    assert r2["status_kind"] == "insufficient" and r2["answer"] == ""


EXAM_TXT = "문 1.\n" + SAMPLE + "\n문 2.\n" + SAMPLE


def test_exam_parse_then_solve_one_by_one(client):
    c = client()
    p = c.post("/api/exam/parse", json={"text": EXAM_TXT}).json()
    assert p["status_kind"] == "ok" and len(p["questions"]) == 2
    r = c.post("/api/exam/solve", json={"batch_id": p["batch_id"], "index": 1}).json()
    assert r["status_kind"] == "ok" and r["index"] == 1 and r["item"]["predicted_label"] == "①"


def test_exam_json_returns_answer_key_but_solver_never_sees_it(client, monkeypatch):
    seen = {}

    class Spy(FakeSolver):
        def solve(self, q, mode=None):
            seen["answer"], seen["accepted"] = q.answer, q.accepted
            return super().solve(q, mode)

    eng = FakeEngine()
    eng.solver = lambda model, preset: Spy()
    monkeypatch.setattr(api, "ENGINE", eng)
    c = TestClient(api.app)
    exam = {"exam": "샘플", "source": "test", "items": [{"id": "T-1", "number": 7, "stem": "옳은 것은?",
                                                       "options": {str(n): f"보기{n}" for n in range(1, 6)}, "answer": 2}]}
    p = c.post("/api/exam/parse", json={"exam": exam}).json()
    assert p["title"] == "샘플" and p["questions"][0]["accepted"] == [2]
    c.post("/api/exam/solve", json={"batch_id": p["batch_id"], "index": 0})
    assert seen == {"answer": None, "accepted": []}


def test_exam_parse_errors_and_expired_batch(client):
    c = client()
    assert c.post("/api/exam/parse", json={"text": "그냥 문장"}).json()["status_kind"] == "error"
    r = c.post("/api/exam/solve", json={"batch_id": "nope", "index": 0}).json()
    assert r["status_kind"] == "error" and r["code"] == "expired"

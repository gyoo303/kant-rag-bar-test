import json

from kant_rag.ingest.cases import build_topics, chunk_cases
from kant_rag.schemas import DocumentMeta

META = DocumentMeta(doc_id="CASES", title="판례", source="t", license="t", version="v", path="x", doc_type="cases")


def test_chunk_cases_items_and_date_cut(tmp_path):
    p = tmp_path / "cases.jsonl"
    rows = [
        {"prec_id": "1", "case_no": "2019다12345", "case_name": "x", "court": "대법원", "decided": "2020.01.09",
         "holding_issue": "[1] 쟁점 일 [2] 쟁점 이", "summary": "[1] 요지 일 <br/>내용 [2] 요지 이",
         "ref_articles": "민법 제126조", "ref_cases": "", "topic": "표현대리"},
        {"prec_id": "2", "case_no": "2026다1", "case_name": "y", "court": "대법원", "decided": "2026.02.01",
         "holding_issue": "", "summary": "시험일 이후", "ref_articles": "", "ref_cases": "", "topic": "t"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    chunks = chunk_cases(p, META, date_to="20251231")
    assert [c.chunk_id for c in chunks] == ["CASE#2019다12345#1", "CASE#2019다12345#2"]
    assert "판시사항: 쟁점 이" in chunks[1].text and "민법 제126조" in chunks[1].text


def test_build_topics_from_statute_structure():
    meta = DocumentMeta(doc_id="LAW", title="민법", source="t", license="t", version="v", path="x", doc_type="statute")
    text = "제1편 총칙\n제5장 법률행위\n제3절 대리\n제114조(대리행위의 효력) 내용\n제115조(목적) 내용"
    topics = build_topics([(meta, text)], level="article")
    assert topics[:3] == ["총칙", "법률행위", "대리"] and "대리행위의 효력" in topics and "목적" not in topics
    assert "대리행위의 효력" not in build_topics([(meta, text)], level="section")


class FakeLawAPI:
    """api-check 진단에서 관찰한 응답 구조(최신순, 2026년 판례 포함)를 흉내."""

    def __init__(self):
        from kant_rag.ingest import lawapi
        self.api = lawapi.LawAPI.__new__(lawapi.LawAPI)
        self.calls = []

        def fake_get(endpoint, **params):
            self.calls.append(params)
            if params["target"] == "prec":
                page = params["page"]
                data = {1: [("2026.08.13", "대법원"), ("2025.06.05", "대법원"), ("2024.01.01", "서울고등법원")],
                        2: [("2023.03.03", "대법원"), ("2010.01.01", "대법원")]}[page]
                return {"PrecSearch": {"totalCnt": 5, "prec": [
                    {"판례일련번호": f"{page}{i}", "선고일자": d, "법원명": c} for i, (d, c) in enumerate(data)]}}
            return {"LawSearch": {"totalCnt": 3, "law": [
                {"법령명한글": "민법", "법령일련번호": "A", "시행일자": "20260317"},
                {"법령명한글": "민법", "법령일련번호": "B", "시행일자": "20250131"},
                {"법령명한글": "난민법", "법령일련번호": "C", "시행일자": "20161220"}]}}
        self.api._get = fake_get


def test_find_law_picks_version_in_force_on_exam_date():
    f = FakeLawAPI()
    assert f.api.find_law("민법", "20260101")["법령일련번호"] == "B"
    assert f.api.find_law("민법")["법령일련번호"] == "A"


def test_search_precs_filters_date_and_court_client_side():
    f = FakeLawAPI()
    hits = f.api.search_precs("표현대리", "20110101", "20251231", want=5, page_size=3)
    assert [h["선고일자"] for h in hits] == ["2025.06.05", "2023.03.03"]
    assert all(c["search"] == 2 and "prncYd" not in c for c in f.calls)


def test_collect_resumes_after_truncated_line(tmp_path):
    out = tmp_path / "cases.jsonl"
    out.write_text('{"prec_id": "11", "summary": "x"}\n{"prec_id": "12", "summ', encoding="utf-8")

    class API:
        def search_precs(self, *a, **k):
            return [{"판례일련번호": "11"}, {"판례일련번호": "13"}]

        def prec(self, pid):
            return {"사건번호": "2020다1", "판결요지": "[1] 요지", "법원명": "대법원", "선고일자": "2020.01.01"}

    from kant_rag.ingest.cases import collect_cases
    stats = collect_cases(API(), ["t"], out, "20110101", "20251231", per_topic=5)
    ids = [json.loads(line)["prec_id"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert ids == ["11", "13"] and stats["new"] == 1

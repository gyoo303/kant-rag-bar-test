import json

from kant_rag.ingest.case_import import import_cases
from kant_rag.ingest.cases import chunk_cases
from kant_rag.schemas import DocumentMeta

KW = dict(date_to="20251231", kinds=["민사", "가사"], codes=["다", "마", "스", "므"], source="t")


def _api(no, kind, date, summary="[1] 요지 <br/>내용"):
    return {"PrecService": {"판례정보일련번호": no, "사건번호": no, "사건명": "x", "법원명": "대법원",
                            "선고일자": date, "사건종류명": kind, "판시사항": "[1] 쟁점", "판결요지": summary,
                            "참조조문": "민법 제1조", "판례내용": "전문" * 1000}}


def test_import_formats_filters_and_dedup(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "a" / "one.json").write_text(json.dumps(_api("2005다1", "민사", "2005.03.04"), ensure_ascii=False), encoding="utf-8")
    (src / "list.json").write_text(json.dumps([_api("2019두2", "일반행정", "20190101"),
                                               _api("2026다3", "민사", "20260301"),
                                               _api("2020다4", "민사", "20200101", summary="")], ensure_ascii=False), encoding="utf-8")
    (src / "lines.jsonl").write_text(json.dumps({"사건번호": "2015스5", "선고일자": "2015.05.05", "판결요지": "요지"},
                                                ensure_ascii=False) + "\n", encoding="utf-8")
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "cases.jsonl").write_text(json.dumps({"prec_id": "9", "case_no": "2015스5", "court": "대법원",
                                                   "decided": "20150505", "summary": "x"}, ensure_ascii=False) + "\n", encoding="utf-8")
    stats = import_cases([src], cases, **KW)
    assert stats["imported"] == 1 and stats["skip_not_civil"] == 1 and stats["skip_after_exam"] == 1
    assert stats["skip_no_summary"] == 1 and stats["skip_duplicate"] == 1
    rec = json.loads((cases / "cases_2005.jsonl").read_text(encoding="utf-8"))
    assert rec["case_no"] == "2005다1" and rec["decided"] == "20050304" and "<br" not in rec["summary"]
    assert "판례내용" not in rec and "전문전문" not in json.dumps(rec, ensure_ascii=False)
    meta = DocumentMeta(doc_id="CASES-SC", title="판례", source="t", license="t", version="v", path="cases", doc_type="cases")
    ids = [c.chunk_id for c in chunk_cases(cases, meta, date_to="20251231", codes=KW["codes"])]
    assert "CASE#2005다1#1" in ids and "CASE#2015스5#1" in ids

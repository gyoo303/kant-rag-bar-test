"""verify-2022 브랜치: 2022년 시험 전 판례만 쓰는 설정과 미래 판례 정보 차단."""
from test_v6 import _corpus, _FakeRetriever, _raw_cases

from kant_rag.config import ROOT, get_settings
from kant_rag.mcq.presets import PRESETS, apply_overrides
from kant_rag.mcq.solver import MCQSolver


def test_branch_config():
    s = get_settings(str(ROOT / "configs" / "default.yaml"))
    assert s.index_path().name == "index-2022@20220101"  # 현재 색인(index/)과 분리, 2022. 1. 1. 법령
    assert s.raw_path("statutes/민법.txt") == ROOT / "data" / "raw" / "statutes@20220101" / "민법.txt"
    assert s.raw_path("statutes/민법.txt").exists() and s.raw_path("statutes/제조물 책임법.txt").exists()
    assert str(s.corpus.case_date_to) == "20220110" and str(s.retrieval.case_date_to) == "20220110"
    assert s.mcq.asof_default == "20220110" and s.mcq.hide_future


def test_hide_future_annotation(tmp_path):
    raw = _raw_cases(tmp_path)
    base = {**PRESETS["v6"], "paths.raw_dir": str(raw.parent), "paths.index_dir": str(tmp_path / "index")}
    chunk = _corpus()["CASE#99다23888#1"]
    show = MCQSolver(apply_overrides(get_settings(), base), retriever=_FakeRetriever(_corpus()))
    assert 'overruled_by="2021다252977' in show._annotator("20220110")(chunk)
    hide = MCQSolver(apply_overrides(get_settings(), {**base, "mcq.hide_future": True}),
                     retriever=_FakeRetriever(_corpus()))
    assert hide._annotator("20220110")(chunk) == ""  # 2025년 변경 판례의 존재를 드러내지 않음
    assert 'overruled_by="2021다252977' in hide._annotator("20251231")(chunk)


def test_alt_circled_options():
    from kant_rag.mcq.parse import parse_exam_text
    text = "문 21.\n\t옳은 것을 모두 고른 것은?\nㄱ.\t가\nㄴ.\t나\n\t①\tㄱ\n\t②\tㄴ\n\t➂\tㄱ, ㄴ\n\t➃\tㄱ\n\t⑤\tㄴ\n"
    q = parse_exam_text(text, "T")[0]
    assert q.options[3] == "ㄱ, ㄴ" and q.options[4] == "ㄱ"

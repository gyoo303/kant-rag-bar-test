import json

from kant_rag.mcq.progress import latest_run, render


def test_progress_table(tmp_path):
    old = tmp_path / "20261124-100000-bar13-v3"
    run = tmp_path / "20261125-090000-bar13-v3"
    old.mkdir(); run.mkdir()
    recs = [{"number": 1, "predicted": 4, "eval": {"kind": "mcq", "answer": 4}, "timing_ms": {"total": 30000}},
            {"number": 2, "predicted": 1, "eval": {"kind": "mcq", "answer": 3}, "timing_ms": {"total": 25000}}]
    (run / "records.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + '\n{"number": 3, "pred',
                                       encoding="utf-8")
    assert latest_run(tmp_path, "bar13-v3") == run
    out = render(run, total=70)
    assert "진행 2/70 · 정답 1/2 (50%)" in out and "오답: [2]" in out
    assert latest_run(tmp_path, "nothing") is None

"""TKT-BE-M2-01: law_collector 출력 읽기 (ADR-015)."""

from __future__ import annotations

import json
from pathlib import Path

from lawqa.corpus.infrastructure.collector_reader import FileCollectorReader


def _write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def test_iter_prec_files_numeric_order_and_broken_json(tmp_path: Path) -> None:
    _write(tmp_path / "prec" / "100.json", json.dumps({"판례정보일련번호": "100"}))
    _write(tmp_path / "prec" / "20.json", json.dumps({"판례정보일련번호": "20"}))
    _write(tmp_path / "prec" / "3.json", "{깨진 JSON")
    _write(tmp_path / "prec" / "list.json", json.dumps([1, 2]))

    files = list(FileCollectorReader().iter_prec_files(tmp_path))

    assert [f.path for f in files] == [
        "prec/3.json",
        "prec/20.json",
        "prec/100.json",
        "prec/list.json",
    ]
    assert files[0].data is None and files[0].error
    assert files[1].data == {"판례정보일련번호": "20"} and files[1].error is None
    assert files[3].data is None and "객체" in (files[3].error or "")


def test_iter_prec_files_missing_directory_yields_nothing(tmp_path: Path) -> None:
    assert list(FileCollectorReader().iter_prec_files(tmp_path)) == []


def test_read_law_text_handles_bom_and_missing_file(tmp_path: Path) -> None:
    reader = FileCollectorReader()
    assert reader.read_law_text(tmp_path) is None

    _write(tmp_path / "law" / "민법.txt", "제1조(법원) 본문\n", encoding="utf-8-sig")

    assert reader.read_law_text(tmp_path) == ("law/민법.txt", "제1조(법원) 본문\n")


def test_list_law_files_reports_all_files(tmp_path: Path) -> None:
    _write(tmp_path / "law" / "민법.txt", "x")
    _write(tmp_path / "law" / "상법.txt", "x")

    assert FileCollectorReader().list_law_files(tmp_path) == ["민법.txt", "상법.txt"]

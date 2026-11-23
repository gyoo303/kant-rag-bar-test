"""문서 목록(manifest) 기반 로딩. 목록에 없는 파일은 색인하지 않습니다."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from kant_rag.schemas import DocumentMeta


@dataclass
class LoadedPage:
    text: str
    page: int | None  # PDF 면 페이지 번호, 텍스트/마크다운이면 None


def read_manifest(manifest_path: Path) -> list[DocumentMeta]:
    with manifest_path.open(encoding="utf-8") as f:
        rows = [DocumentMeta(**{k: (v or None) if k == "department" else v for k, v in r.items()})
                for r in csv.DictReader(f)]
    ids = [r.doc_id for r in rows]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"중복 doc_id: {sorted(dup)}")
    return rows


def load_pages(path: Path) -> list[LoadedPage]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [LoadedPage(text=p.extract_text() or "", page=i + 1)
                for i, p in enumerate(reader.pages)]
    if suffix in {".md", ".txt"}:
        return [LoadedPage(text=path.read_text(encoding="utf-8"), page=None)]
    raise ValueError(f"지원하지 않는 형식: {path}")


def clean_text(text: str) -> str:
    """최소 정제: 개행 통일, 행 끝 공백 제거. 행 번호가 바뀌지 않도록 행은 삭제하지 않습니다."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    return "\n".join(line.rstrip() for line in text.split("\n"))

"""원문 위치(절·행·페이지)를 보존하는 청킹.

- 마크다운 heading 으로 절을 나누고, 절 안에서 chunk_size 단위로 문단을 묶습니다.
- 청크 ID 는 `{doc_id}#{절 순번:02d}-{청크 순번:02d}` 로, 같은 문서·같은 설정이면 항상 동일합니다.
  (청킹 설정을 바꾸면 ID 가 바뀔 수 있으므로 eval 근거 매핑을 갱신하고 index 버전을 올리세요.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kant_rag.schemas import Chunk, DocumentMeta

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class _Line:
    no: int  # 1-based
    text: str
    char_start: int


@dataclass
class _Section:
    path: str
    lines: list[_Line]


def _split_sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    stack: list[str] = []
    current = _Section(path="", lines=[])
    offset = 0
    for i, raw in enumerate(text.split("\n"), start=1):
        m = HEADING.match(raw)
        if m:
            if current.lines:
                sections.append(current)
            level = len(m.group(1))
            stack = stack[: level - 1] + [m.group(2).strip()]
            current = _Section(path=" > ".join(stack), lines=[])
        current.lines.append(_Line(no=i, text=raw, char_start=offset))
        offset += len(raw) + 1
    if current.lines:
        sections.append(current)
    return sections


def chunk_text(
    text: str,
    meta: DocumentMeta,
    chunk_size: int,
    chunk_overlap: int,
    page: int | None = None,
    section_offset: int = 0,
) -> list[Chunk]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 은 chunk_size 보다 작아야 합니다")
    chunks: list[Chunk] = []
    for s_idx, sec in enumerate(_split_sections(text), start=section_offset):
        lines = [ln for ln in sec.lines if ln.text.strip()]
        if not lines or all(HEADING.match(ln.text) for ln in lines):
            continue
        start = 0
        c_idx = 0
        while start < len(lines):
            end, size = start, 0
            while end < len(lines) and (size == 0 or size + len(lines[end].text) <= chunk_size):
                size += len(lines[end].text) + 1
                end += 1
            window = lines[start:end]
            body = "\n".join(ln.text for ln in window)
            prefix = f"[{meta.title}] {sec.path}\n" if sec.path else f"[{meta.title}]\n"
            chunks.append(
                Chunk(
                    chunk_id=f"{meta.doc_id}#{('p%d-' % page) if page else ''}{s_idx:02d}-{c_idx:02d}",
                    doc_id=meta.doc_id,
                    title=meta.title,
                    text=prefix + body,
                    section=sec.path or None,
                    page=page,
                    line_start=window[0].no,
                    line_end=window[-1].no,
                    char_start=window[0].char_start,
                    char_end=window[-1].char_start + len(window[-1].text),
                    metadata={
                        "source": meta.source,
                        "version": meta.version,
                        "department": meta.department,
                    },
                )
            )
            c_idx += 1
            if end >= len(lines):
                break
            # 겹침: 뒤에서부터 chunk_overlap 문자만큼 행을 되돌림 (최소 1행 전진 보장)
            back, ov = end, 0
            while back - 1 > start and ov < chunk_overlap:
                back -= 1
                ov += len(lines[back].text) + 1
            start = max(back, start + 1)
    return chunks

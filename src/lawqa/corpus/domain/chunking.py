"""청킹 규칙 (03-db-schema §4, AQ-004·007). 순수 함수, 표준 라이브러리만 사용.

- 조문: 조문 1개 = 청크 1개. 길면 항(①②…) 경계로 묶어 나누고 위치에 `제a항~제b항`을 붙인다.
- 판례: 판시사항 `[n]`과 판결요지 `[n]`을 같은 번호끼리 묶어 청크 1개. 한쪽이라도 번호 표시가
  없으면 판시사항+판결요지 전체가 청크 1개. 길면 문장 경계로 나누고 `overlap_chars`만큼 겹친다.
- 항목 표시는 줄 머리의 `[n]`만 인정한다(본문 안의 "[1]항의" 같은 참조는 나누지 않음).
- 청크 본문 첫 줄 = 원문 위치(+ 조문 제목, + 판례 참조조문). seq는 문서 안 순번(1부터).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from lawqa.corpus.domain.models import Chunk, DocumentKind, SourceDocument, SourceLocation

_ITEM_MARK = re.compile(r"^[ \t]*\[(\d+)\][ \t]*", re.MULTILINE)
_PARAGRAPH_MARK = re.compile(r"^([①-⑳])")  # ①~⑳
_SENTENCE_END = re.compile(r"(?<=[.?!다])\s+")
# 청크 첫 줄에 보여 줄 참조조문 최대 글자 수. 전체는 Chunk.referenced_articles에 그대로 둔다
# (실제 수집분에서 참조조문이 1,900자를 넘는 판례가 있어 머리줄이 max_chars를 넘었음)
REFERENCE_HEADER_MAX = 300


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    max_chars: int
    overlap_chars: int

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars는 1 이상이어야 합니다.")
        if not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars는 0 이상 max_chars 미만이어야 합니다.")

    def split(
        self, doc: SourceDocument, index_version: str, tokenize: Callable[[str], list[str]]
    ) -> list[Chunk]:
        if doc.kind is DocumentKind.STATUTE_ARTICLE:
            pieces = self._article_pieces(doc)
            section = "ARTICLE"
        else:
            pieces = self._precedent_pieces(doc)
            section = "HOLDING"
        chunks = []
        for seq, (location, text) in enumerate(pieces, start=1):
            chunks.append(
                Chunk(
                    index_version=index_version,
                    chunk_id=f"{doc.doc_id}#{section}#{seq}",
                    doc_id=doc.doc_id,
                    kind=doc.kind,
                    section=section,
                    seq=seq,
                    location=location,
                    text=text,
                    referenced_articles=doc.referenced_articles,
                    bm25_tokens=tuple(tokenize(text)),
                )
            )
        return chunks

    # ── 조문 ──
    def _article_pieces(self, doc: SourceDocument) -> list[tuple[SourceLocation, str]]:
        no, branch = doc.article_no or 0, doc.article_branch_no
        whole = SourceLocation.for_article(no, branch, None)
        heading = whole.text + (f"({doc.article_title})" if doc.article_title else "")
        body = doc.body or ""
        if len(heading) + 1 + len(body) <= self.max_chars:
            return [(whole, f"{heading}\n{body}")]

        groups = _paragraph_groups(body)
        limit = self.max_chars - len(heading) - len(" 제00항~제00항") - 1
        pieces: list[tuple[SourceLocation, str]] = []
        batch: list[tuple[int | None, str]] = []
        for group in groups:
            if batch and _joined_len(batch) + 1 + len(group[1]) > limit:
                pieces.extend(self._article_batch(no, branch, heading, batch, limit))
                batch = []
            batch.append(group)
        if batch:
            pieces.extend(self._article_batch(no, branch, heading, batch, limit))
        return pieces

    def _article_batch(
        self,
        no: int,
        branch: int,
        heading: str,
        batch: list[tuple[int | None, str]],
        limit: int,
    ) -> list[tuple[SourceLocation, str]]:
        numbers = [n for n, _ in batch if n is not None]
        if numbers:
            first, last = numbers[0], numbers[-1]
            label = f"제{first}항" if first == last else f"제{first}항~제{last}항"
        else:
            label = None
        location = SourceLocation.for_article(no, branch, label)
        head = location.text + heading[len(SourceLocation.article_label(no, branch)) :]
        text = "\n".join(part for _, part in batch)
        return [(location, f"{head}\n{part}") for part in self._sized(text, limit)]

    # ── 판례 ──
    def _precedent_pieces(self, doc: SourceDocument) -> list[tuple[SourceLocation, str]]:
        holdings = _items(doc.holdings or "")
        summary = _items(doc.summary or "")
        groups: list[tuple[int | None, str]] = []
        if holdings is not None and summary is not None:
            for number in sorted(set(holdings) | set(summary)):
                groups.append((number, _holding_text(holdings.get(number), summary.get(number))))
        else:
            groups.append((None, _holding_text(doc.holdings, doc.summary)))

        pieces: list[tuple[SourceLocation, str]] = []
        for number, body in groups:
            location = SourceLocation.for_precedent(
                doc.decided_on or date.min, doc.case_number or "", number, doc.court or "대법원"
            )
            head = location.text + _reference_suffix(doc.referenced_articles)
            limit = max(self.max_chars - len(head) - 1, self.overlap_chars + 1)
            for part in self._sized(body, limit):
                pieces.append((location, f"{head}\n{part}"))
        return pieces

    # ── 길이 맞추기 ──
    def _sized(self, text: str, limit: int) -> list[str]:
        """`limit` 글자 이하 조각으로 나눈다. 문장 경계 우선, 다음 조각은 앞 조각 끝을 겹친다."""
        text = text.strip()
        if len(text) <= limit:
            return [text]
        overlap = min(self.overlap_chars, limit // 2)
        sentences = [s for s in _SENTENCE_END.split(text) if s]
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            while len(sentence) > limit:  # 한 문장이 너무 길면 글자 수로 자른다
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(sentence[:limit])
                sentence = sentence[limit - overlap :] if overlap else sentence[limit:]
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= limit:
                current = candidate
                continue
            pieces.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
            if len(current) > limit:
                current = sentence
        if current:
            pieces.append(current)
        return pieces


def _items(text: str) -> dict[int, str] | None:
    """줄 머리 `[n]`으로 항목을 나눈다. 표시가 없으면 None."""
    marks = list(_ITEM_MARK.finditer(text))
    if not marks:
        return None
    items: dict[int, str] = {}
    for current, following in zip(marks, [*marks[1:], None], strict=True):
        end = following.start() if following else len(text)
        body = text[current.end() : end].strip()
        number = int(current.group(1))
        items[number] = f"{items[number]}\n{body}" if number in items else body
    return items


def _reference_suffix(references: str | None) -> str:
    """청크 머리줄의 참조조문 부분. 줄바꿈은 공백으로, 길면 잘라 `…`를 붙인다."""
    if not references:
        return ""
    flat = " ".join(references.split())
    if len(flat) > REFERENCE_HEADER_MAX:
        flat = flat[: REFERENCE_HEADER_MAX - 1] + "…"
    return f" | 참조조문: {flat}"


def _holding_text(holdings: str | None, summary: str | None) -> str:
    parts = []
    if holdings and holdings.strip():
        parts.append(f"[판시사항] {holdings.strip()}")
    if summary and summary.strip():
        parts.append(f"[판결요지] {summary.strip()}")
    return "\n".join(parts)


def _paragraph_groups(body: str) -> list[tuple[int | None, str]]:
    """조문 본문을 항(①…) 단위로 묶는다. ① 앞의 줄은 첫 묶음에 붙인다."""
    groups: list[tuple[int | None, str]] = []
    for line in body.splitlines():
        mark = _PARAGRAPH_MARK.match(line)
        if mark or not groups:
            number = ord(mark.group(1)) - 0x245F if mark else None
            groups.append((number, line))
        else:
            number, text = groups[-1]
            groups[-1] = (number, f"{text}\n{line}")
    return groups


def _joined_len(batch: list[tuple[int | None, str]]) -> int:
    return sum(len(text) for _, text in batch) + max(len(batch) - 1, 0)

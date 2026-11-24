"""corpus 도메인: 원문 문서·원문 위치·청크·색인 판본·가져오기 문제 (04-interfaces-api §1.2).

원문 변환 규칙은 ADR-015(판례 `PrecService` JSON, 민법 일반 텍스트)를 따른다.
표준 라이브러리와 `lawqa.shared.versioning`만 쓴다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from lawqa.corpus.domain.errors import (
    BAD_DATE,
    DUPLICATE_ARTICLE,
    EMPTY_CONTENT,
    MISSING_FIELD,
    InvalidSourceDocumentError,
    OutOfScopeError,
)
from lawqa.corpus.domain.text_clean import clean_text
from lawqa.shared.versioning import sha256_of

CIVIL_CASE_TYPE = "민사"
# 청킹·원문 변환 규칙이 바뀌면 올린다(색인 판본 id에 들어감, INV-11)
CHUNKING_RULES_VERSION = "1"


class DocumentKind(StrEnum):
    STATUTE_ARTICLE = "STATUTE_ARTICLE"
    PRECEDENT = "PRECEDENT"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """원문 위치 문자열(03-db-schema §4). 검색·인용에 같은 문자열을 쓴다."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("원문 위치가 비어 있습니다.")

    @staticmethod
    def article_label(law_name: str, no: int, branch: int) -> str:
        return f"{law_name} 제{no}조" + (f"의{branch}" if branch else "")

    @staticmethod
    def for_article(
        law_name: str, no: int, branch: int, paragraph_range: str | None
    ) -> SourceLocation:
        """`민법 제245조`, `상법 제14조의2`, 나눈 경우 `민사소송법 제103조 제3항~제5항`."""
        label = SourceLocation.article_label(law_name, no, branch)
        return SourceLocation(f"{label} {paragraph_range}" if paragraph_range else label)

    @staticmethod
    def for_precedent(
        decided_on: date, case_number: str, item_no: int | None, court: str = "대법원"
    ) -> SourceLocation:
        """`대법원 2019. 1. 31. 선고 2016다215127 판결 [1]` (하급심이면 그 법원명)."""
        day = f"{decided_on.year}. {decided_on.month}. {decided_on.day}."
        text = f"{court} {day} 선고 {case_number} 판결"
        return SourceLocation(f"{text} [{item_no}]" if item_no is not None else text)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """가져온 원문 1건(ENT-01).

    판례는 판시사항·판결요지 중 하나, 조문은 본문·조문번호가 필수(INV-02).
    """

    doc_id: str
    kind: DocumentKind
    title: str
    source_file: str
    source_line: int
    content_sha: str
    case_number: str | None = None
    decided_on: date | None = None
    court: str | None = None
    case_type: str | None = None
    holdings: str | None = None
    summary: str | None = None
    referenced_articles: str | None = None
    law_name: str | None = None
    article_no: int | None = None
    article_branch_no: int = 0
    article_title: str | None = None
    body: str | None = None
    effective_on: date | None = None

    def __post_init__(self) -> None:
        if not self.doc_id or not self.title.strip():
            raise InvalidSourceDocumentError(MISSING_FIELD, "doc_id·title")
        if self.source_line < 1:
            raise InvalidSourceDocumentError(MISSING_FIELD, "source_line")
        if self.kind is DocumentKind.PRECEDENT:
            if not ((self.holdings or "").strip() or (self.summary or "").strip()):
                raise InvalidSourceDocumentError(
                    EMPTY_CONTENT, f"{self.doc_id}: 판시사항·판결요지 없음"
                )
        elif not ((self.body or "").strip() and self.article_no is not None):
            raise InvalidSourceDocumentError(EMPTY_CONTENT, f"{self.doc_id}: 조문 본문 없음")
        elif not (self.law_name or "").strip():
            # 법령이 여럿이므로 조문은 법령 이름 없이 원문 위치를 만들 수 없다(CR-009·010).
            raise InvalidSourceDocumentError(MISSING_FIELD, f"{self.doc_id}: law_name")

    @property
    def location(self) -> SourceLocation:
        """문서 전체의 원문 위치(항목 번호 없음)."""
        if self.kind is DocumentKind.STATUTE_ARTICLE:
            return SourceLocation.for_article(
                self.law_name or "", self.article_no or 0, self.article_branch_no, None
            )
        return SourceLocation.for_precedent(
            self.decided_on or date.min, self.case_number or "", None, self.court or "대법원"
        )

    @classmethod
    def from_prec_service(cls, obj: Mapping[str, Any], source_file: str) -> SourceDocument:
        """`law_collector`가 저장한 `PrecService` JSON 1건을 변환한다(ADR-015).

        민사만(`사건종류명 == "민사"`), 법원명은 거르지 않는다. 규칙에 어긋나면
        `InvalidSourceDocumentError`(`reason`이 import_issues 사유).
        """
        serial = _required(obj, "판례정보일련번호")
        case_type = clean_text(_text(obj, "사건종류명"))
        if case_type != CIVIL_CASE_TYPE:
            raise OutOfScopeError(f"사건종류명={case_type or '없음'}")
        case_number = clean_text(_required(obj, "사건번호"))
        court = clean_text(_required(obj, "법원명"))
        decided_on = _parse_date(_text(obj, "선고일자"), "선고일자")
        holdings = clean_text(_text(obj, "판시사항")) or None
        summary = clean_text(_text(obj, "판결요지")) or None
        references = clean_text(_text(obj, "참조조문")) or None
        title = clean_text(_text(obj, "사건명")) or case_number
        content = {
            "case_number": case_number,
            "court": court,
            "decided_on": decided_on.isoformat(),
            "title": title,
            "holdings": holdings,
            "summary": summary,
            "referenced_articles": references,
        }
        return cls(
            doc_id=f"prec:{serial}",
            kind=DocumentKind.PRECEDENT,
            title=title,
            source_file=source_file,
            source_line=1,
            content_sha=_content_sha(content),
            case_number=case_number,
            decided_on=decided_on,
            court=court,
            case_type=case_type,
            holdings=holdings,
            summary=summary,
            referenced_articles=references,
        )

    @staticmethod
    def statute_articles_from_text(
        text: str, source_file: str, law_name: str
    ) -> tuple[list[SourceDocument], StatuteParseReport]:
        """법령 일반 텍스트를 조문 단위로 나눈다(ADR-015 표의 규칙, CR-010).

        `law_name`은 파일 이름(확장자 제외)이고 `doc_id = "law:<law_name>:<조>-<가지>"`가 된다.
        """
        return _parse_statute_text(text, source_file, law_name)


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """가져오기 문제 1건(REJ-06). `reason`은 errors 모듈의 사유 값(필요하면 `:<필드>`)."""

    source_file: str
    source_line: int
    reason: str

    def __post_init__(self) -> None:
        if self.source_line < 1 or not self.reason:
            raise ValueError("source_line은 1 이상, reason은 비어 있지 않아야 합니다.")


@dataclass(frozen=True, slots=True)
class StatuteParseReport:
    """민법 텍스트 파싱 결과 요약. 삭제 조문·제목 줄은 오류가 아니라 제외 건수다."""

    articles: int
    deleted: int
    headings: int
    dropped_lines: int
    issues: tuple[ImportIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Chunk:
    """검색 단위(ENT-02). chunk_id = `<doc_id>#<section>#<seq>`."""

    index_version: str
    chunk_id: str
    doc_id: str
    kind: DocumentKind
    section: Literal["ARTICLE", "HOLDING"]
    seq: int
    location: SourceLocation
    text: str
    referenced_articles: str | None
    bm25_tokens: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise ValueError("seq는 1 이상이어야 합니다.")
        if self.section not in ("ARTICLE", "HOLDING"):
            raise ValueError(f"알 수 없는 section: {self.section}")
        if not self.text.strip():
            raise ValueError("청크 본문이 비어 있습니다.")
        if not (self.index_version and self.doc_id):
            raise ValueError("index_version·doc_id가 필요합니다(INV-02).")
        if self.chunk_id != f"{self.doc_id}#{self.section}#{self.seq}":
            raise ValueError(f"chunk_id 형식이 다릅니다: {self.chunk_id}")


@dataclass(frozen=True, slots=True)
class IndexVersion:
    """색인 판본(ENT-03). id는 원문 판본·청킹 설정·임베딩 설정으로 정해진다(INV-11)."""

    index_version: str
    corpus_version: str
    max_chars: int
    overlap_chars: int
    embedding_model: str
    embedding_dim: int
    created_at: datetime
    doc_count: int = 0
    chunk_count: int = 0
    skipped_count: int = 0
    complete: bool = False

    @staticmethod
    def compute_id(
        corpus_version: str, policy: Any, embedding_model: str, embedding_dim: int
    ) -> str:
        """`idx-<corpus_version 앞 8자>-<청킹·임베딩 설정 해시 앞 8자>`.

        `policy`는 `max_chars`·`overlap_chars` 속성을 가진 `ChunkingPolicy`.
        """
        settings = (
            f"rules={CHUNKING_RULES_VERSION}|max={policy.max_chars}|overlap={policy.overlap_chars}"
            f"|model={embedding_model}|dim={embedding_dim}"
        )
        return f"idx-{corpus_version[:8]}-{sha256_of(settings.encode())[:8]}"

    def collection_name(self) -> str:
        """PGVector 컬렉션 이름(03-db-schema §3 ENT-05)."""
        return collection_name_for(self.index_version)


def collection_name_for(index_version: str) -> str:
    return f"chunks_{index_version}"


# ───────────────────────── 판례 변환 도우미 ─────────────────────────
def _text(obj: Mapping[str, Any], key: str) -> str:
    value = obj.get(key)
    return "" if value is None else str(value)


def _required(obj: Mapping[str, Any], key: str) -> str:
    value = _text(obj, key).strip()
    if not value:
        raise InvalidSourceDocumentError(f"{MISSING_FIELD}:{key}")
    return value


def _parse_date(value: str, field_name: str) -> date:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        raise InvalidSourceDocumentError(f"{BAD_DATE}:{field_name}", value)
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    except ValueError as exc:
        raise InvalidSourceDocumentError(f"{BAD_DATE}:{field_name}", value) from exc


def _content_sha(content: Mapping[str, Any]) -> str:
    return sha256_of(json.dumps(content, ensure_ascii=False, sort_keys=True).encode())


# ───────────────────────── 민법 텍스트 파서 (ADR-015) ─────────────────────────
_HEADING = re.compile(r"^제\d+(?:편|장|절|관)(?:의\d+)?\s")
_SPECIAL_HEADING = re.compile(r"^제\d+항\s+\S")
_ARTICLE_HEAD = re.compile(
    r"^제(?P<no>\d+)조(?:의(?P<branch>\d+))?\s*"
    r"(?:\((?P<t1>[^)]*)\)|\[(?P<t2>.*?)\](?=\S|$))?\s*(?P<rest>.*)$"
)
_DELETED_ITEM = re.compile(r"^\d+(?:의\d+)?\.\s*삭제")
_AMENDMENT_TAG = re.compile(
    r"\s*<(?:개정|신설|전문개정|본조신설|제목개정)[^>]*>|\s*<\d{4}\.\d{1,2}\.\d{1,2}>"
)


@dataclass(slots=True)
class _Article:
    no: int
    branch: int
    title: str
    line_no: int
    lines: list[str]


def _parse_statute_text(
    text: str, source_file: str, law_name: str
) -> tuple[list[SourceDocument], StatuteParseReport]:
    raw_lines = text.lstrip("﻿").splitlines()
    lines = [_AMENDMENT_TAG.sub("", raw.strip()).strip() for raw in raw_lines]
    articles: list[_Article] = []
    current: _Article | None = None
    deleted = headings = dropped = 0

    for index, line in enumerate(lines):
        if not line:
            continue
        if _HEADING.match(line) or (
            _SPECIAL_HEADING.match(line) and _next_is_article_head(lines, index)
        ):
            current = None
            headings += 1
            continue
        head = _ARTICLE_HEAD.match(line)
        if head:
            rest = head.group("rest").strip()
            if rest.startswith("삭제"):
                current = None
                deleted += 1
                continue
            current = _Article(
                no=int(head.group("no")),
                branch=int(head.group("branch") or 0),
                title=(head.group("t1") or head.group("t2") or "").strip(),
                line_no=index + 1,
                lines=[rest] if rest else [],
            )
            articles.append(current)
            continue
        if _DELETED_ITEM.match(line):
            continue
        if current is None:
            dropped += 1
            continue
        current.lines.append(line)

    documents: list[SourceDocument] = []
    issues: list[ImportIssue] = []
    seen: set[str] = set()
    for article in articles:
        doc_id = f"law:{law_name}:{article.no}-{article.branch}"
        if doc_id in seen:
            issues.append(ImportIssue(source_file, article.line_no, DUPLICATE_ARTICLE))
            continue
        seen.add(doc_id)
        body = "\n".join(article.lines).strip()
        if not body:
            issues.append(ImportIssue(source_file, article.line_no, EMPTY_CONTENT))
            continue
        label = SourceLocation.article_label(law_name, article.no, article.branch)
        title = f"{label}({article.title})" if article.title else label
        content = {"no": article.no, "branch": article.branch, "title": article.title, "body": body}
        documents.append(
            SourceDocument(
                doc_id=doc_id,
                kind=DocumentKind.STATUTE_ARTICLE,
                title=title,
                source_file=source_file,
                source_line=article.line_no,
                content_sha=_content_sha(content),
                law_name=law_name,
                article_no=article.no,
                article_branch_no=article.branch,
                article_title=article.title or None,
                body=body,
            )
        )
    report = StatuteParseReport(
        articles=len(documents),
        deleted=deleted,
        headings=headings,
        dropped_lines=dropped,
        issues=tuple(issues),
    )
    return documents, report


def _next_is_article_head(lines: list[str], index: int) -> bool:
    for line in lines[index + 1 :]:
        if line:
            return bool(_ARTICLE_HEAD.match(line))
    return False


def corpus_version_of(content_shas: Iterable[str]) -> str:
    """원문 판본: 원문들의 `content_sha`를 정렬해 합친 해시(03-db-schema §3 index_versions)."""
    return sha256_of("\n".join(sorted(content_shas)).encode())

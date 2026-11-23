"""파이프라인 전 구간에서 공유하는 데이터 규격."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DocumentMeta(BaseModel):
    doc_id: str
    title: str
    source: str
    license: str
    version: str
    collected_at: str = ""  # 수집 전이면 빈 값
    path: str
    doc_type: str = "general"  # statute(법령: 조문 단위 청킹) | case(판례) | general
    department: str | None = None


class Chunk(BaseModel):
    chunk_id: str  # 안정적 ID: {doc_id}#{section_slug}#{순번}
    doc_id: str
    title: str
    text: str
    section: str | None = None  # 원문 절(heading) 경로
    page: int | None = None  # PDF 페이지 (1-based)
    line_start: int | None = None  # 원문 행 범위 (1-based, 포함)
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    metadata: dict = Field(default_factory=dict)

    def location(self) -> str:
        parts = []
        if self.page is not None:
            parts.append(f"p.{self.page}")
        if self.section:
            parts.append(f"§ {self.section}")
        if self.line_start is not None:
            parts.append(f"L{self.line_start}-{self.line_end}")
        return " / ".join(parts) or "-"


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    rank: int  # 1-based
    source: Literal["vector", "bm25", "rrf", "rerank"]
    # 단계별 순위/점수 기록 (재정렬 전후 비교용)
    trace: dict[str, float | int | None] = Field(default_factory=dict)


class AnswerStatus(str, Enum):
    OK = "ok"  # 근거 기반 답변
    INSUFFICIENT = "insufficient_evidence"  # 정상적인 '근거 없음' 안내
    RETRIEVAL_ERROR = "retrieval_error"  # 검색 실패 (근거 없음과 구분!)
    GENERATION_ERROR = "generation_error"  # 모델 호출/파싱 실패
    INVALID_CITATION = "invalid_citation"  # 검색되지 않은 청크를 인용


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    location: str
    quote: str  # 원문 발췌 (검색된 청크 텍스트에서 가져옴)


class AnswerResult(BaseModel):
    question: str
    answer: str
    status: AnswerStatus
    citations: list[Citation] = Field(default_factory=list)
    error: str | None = None


class LLMAnswer(BaseModel):
    """LLM 구조화 출력 스키마."""

    answerable: bool = Field(description="제공된 근거만으로 답할 수 있으면 true")
    answer: str = Field(description="근거에 기반한 한국어 답변. 답할 수 없으면 정보 부족 안내")
    cited_chunk_ids: list[str] = Field(
        default_factory=list, description="답변의 주요 주장을 뒷받침하는 청크 ID 목록"
    )

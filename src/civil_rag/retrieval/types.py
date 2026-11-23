"""검색 결과 자료형. 실행 기록에 그대로 직렬화된다."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Candidate:
    chunk_id: str
    doc_id: str
    section: str
    text: str
    metadata: dict = field(default_factory=dict)
    # 단계별 점수·순위 (없으면 None). 순위는 1부터.
    bm25_score: float | None = None
    bm25_rank: int | None = None
    vector_score: float | None = None   # 코사인 유사도(높을수록 관련). pgvector 거리는 1-거리로 변환
    vector_rank: int | None = None
    fused_score: float | None = None    # 가중 RRF
    fused_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None

    def cite_label(self) -> str:
        m = self.metadata
        if m.get("doc_type") == "law":
            return f"{m.get('law_name', '')} {m.get('article', self.section)}".strip()
        return f"{m.get('court', '')} {m.get('decision_date', '')} 선고 {m.get('case_no', '')} [{self.section}]".strip()

    def to_record(self, with_text: bool = False, excerpt_len: int = 200) -> dict:
        d = asdict(self)
        body = self.text.split("\n", 1)[-1]
        d["excerpt"] = body[:excerpt_len]
        d["label"] = self.cite_label()
        if not with_text:
            d.pop("text")
        return d


@dataclass
class RetrievalResult:
    config: str                      # A | B | C
    query: str                       # 검색에 실제 쓴 질의 (리라이트 적용 시 변환 질의)
    original_query: str
    rewritten_query: str | None
    rewrite_status: str | None       # ok | fallback | None
    final: list[Candidate]           # 최종 근거 (FINAL_K개 이하)
    stages: dict[str, list[str]] = field(default_factory=dict)   # 단계별 chunk_id 순위
    timings: dict[str, float] = field(default_factory=dict)      # 초
    gated_out: bool = False          # 근거 부족 임계값에 걸려 전부 제외됐는지

    def to_record(self) -> dict:
        return {
            "config": self.config,
            "query": self.query,
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "rewrite_status": self.rewrite_status,
            "final": [c.to_record() for c in self.final],
            "stages": self.stages,
            "timings": self.timings,
            "gated_out": self.gated_out,
        }

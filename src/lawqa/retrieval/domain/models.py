"""retrieval 도메인 모델 (04-interfaces-api §1.3, ADR-011). 표준 라이브러리만 사용."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from lawqa.retrieval.domain.errors import InvalidExamItemError

OPTION_COUNT = 5
STEM_MAX_CHARS = 4000
OPTION_MAX_CHARS = 1000
DEFAULT_QUESTION_LIST_MAX = 20  # ADR-011: 문항 목록 길이 최대 20

ConfigName = Literal["A", "B", "C", "C+R"]


@dataclass(frozen=True, slots=True)
class ExamItem:
    """입력 문항(지문 + 보기 5개). 규칙을 어기면 `InvalidExamItemError`(R-3, AC-09-4)."""

    stem: str
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stem, str) or not self.stem.strip():
            raise InvalidExamItemError("stem", "지문이 비어 있습니다.")
        if len(self.stem) > STEM_MAX_CHARS:
            raise InvalidExamItemError(
                "stem", f"지문은 {STEM_MAX_CHARS:,}자 이하여야 합니다(현재 {len(self.stem):,}자)."
            )
        if isinstance(self.options, str) or not isinstance(self.options, Iterable):
            raise InvalidExamItemError("options", "보기는 목록이어야 합니다.")
        options = tuple(self.options)
        if len(options) != OPTION_COUNT:
            raise InvalidExamItemError(
                "options", f"보기는 정확히 {OPTION_COUNT}개여야 합니다(현재 {len(options)}개)."
            )
        for no, option in enumerate(options, start=1):
            where = f"options[{no}]"
            if not isinstance(option, str) or not option.strip():
                raise InvalidExamItemError(where, f"보기 {no}이 비어 있습니다.")
            if len(option) > OPTION_MAX_CHARS:
                raise InvalidExamItemError(
                    where, f"보기 {no}은 {OPTION_MAX_CHARS:,}자 이하여야 합니다({len(option):,}자)."
                )
        object.__setattr__(self, "options", options)


class RetrievalMode(StrEnum):
    A = "A"  # 벡터
    B = "B"  # BM25 + 벡터 → RRF
    C = "C"  # B + 재정렬


_MODE_OF: dict[str, RetrievalMode] = {
    "A": RetrievalMode.A,
    "B": RetrievalMode.B,
    "C": RetrievalMode.C,
    "C+R": RetrievalMode.C,
}


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """검색 구성. 이름과 모드·리라이트가 맞아야 한다(`C+R`만 리라이트)."""

    name: ConfigName
    mode: RetrievalMode
    use_rewrite: bool
    n_vec: int
    n_bm25: int
    n_fuse: int
    k_opt: int
    rrf_c: int
    weights: tuple[float, float]
    # CR-018: 보기별 상위 k_opt 안에 보장할 조문 수. 0이면 몫을 두지 않는다.
    k_law: int = 0

    def __post_init__(self) -> None:
        want = _MODE_OF.get(self.name)
        if want is None:
            raise ValueError(f"알 수 없는 구성 이름: {self.name!r}")
        if self.mode is not want:
            raise ValueError(f"구성 {self.name}의 모드는 {want.value}여야 합니다: {self.mode}")
        if self.use_rewrite != (self.name == "C+R"):
            raise ValueError(f"리라이트는 C+R 구성만 씁니다(구성 {self.name}).")
        for key in ("n_vec", "n_bm25", "n_fuse", "k_opt", "rrf_c"):
            if getattr(self, key) < 1:
                raise ValueError(f"{key}는 1 이상이어야 합니다.")
        if not 0 <= self.k_law <= self.k_opt:
            raise ValueError(f"k_law는 0 이상 k_opt({self.k_opt}) 이하여야 합니다: {self.k_law}")
        weights = tuple(float(w) for w in self.weights)
        if len(weights) != 2 or min(weights) < 0 or sum(weights) <= 0:
            raise ValueError(f"weights는 0 이상 숫자 2개이고 합이 0보다 커야 합니다: {weights}")
        object.__setattr__(self, "weights", weights)

    @property
    def comparable_key(self) -> tuple[int, int, int, int, int, tuple[float, float], int]:
        """구성끼리 같아야 하는 값(이름·모드·리라이트를 뺀 나머지, INV-08). k_law 포함(CR-018)."""
        return (
            self.n_vec,
            self.n_bm25,
            self.n_fuse,
            self.k_opt,
            self.rrf_c,
            self.weights,
            self.k_law,
        )


@dataclass(frozen=True, slots=True)
class OptionQuery:
    """보기 하나의 검색 질의. 리라이트 결과가 있으면 그것으로 검색한다(INV-10)."""

    option_no: int
    original: str
    rewritten: str | None = None
    fallback: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.option_no <= OPTION_COUNT:
            raise ValueError(f"option_no는 1..{OPTION_COUNT}이어야 합니다: {self.option_no}")
        if not self.original.strip():
            raise ValueError("original 질의가 비어 있습니다.")
        if self.rewritten is not None and not self.rewritten.strip():
            raise ValueError("rewritten이 있으면 비어 있지 않아야 합니다.")
        if self.fallback and self.rewritten is not None:
            raise ValueError("fallback이면 rewritten이 없어야 합니다(원 질의로 검색).")

    @property
    def effective(self) -> str:
        return self.rewritten if self.rewritten is not None else self.original


@dataclass(frozen=True, slots=True)
class Candidate:
    """검색 후보 청크 하나. 단계별 순위·점수(없는 값은 None)."""

    chunk_id: str
    doc_id: str
    location: str
    text: str
    bm25_rank: int | None = None
    bm25_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    fused_rank: int | None = None
    rerank_score: float | None = None
    final_rank: int | None = None

    def __post_init__(self) -> None:
        if not (self.chunk_id and self.doc_id and self.location):
            raise ValueError("chunk_id·doc_id·location이 필요합니다(INV-02).")
        for key in ("bm25_rank", "vector_rank", "fused_rank", "final_rank"):
            rank = getattr(self, key)
            if rank is not None and rank < 1:
                raise ValueError(f"{key}는 1 이상이어야 합니다: {rank}")


@dataclass(frozen=True, slots=True)
class OptionResult:
    """보기 하나의 최종 목록(`final_rank` 오름차순, 청크 중복 없음)."""

    query: OptionQuery
    candidates: tuple[Candidate, ...]

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        ranks = [c.final_rank for c in candidates if c.final_rank is not None]
        if len(ranks) != len(candidates):
            raise ValueError("후보마다 final_rank가 있어야 합니다.")
        if any(a >= b for a, b in zip(ranks, ranks[1:], strict=False)):
            raise ValueError("후보는 final_rank 오름차순이고 순위가 겹치지 않아야 합니다.")
        if len({c.chunk_id for c in candidates}) != len(candidates):
            raise ValueError("보기 목록 안에 같은 청크가 두 번 있습니다.")
        object.__setattr__(self, "candidates", candidates)

    def top(self, k: int) -> tuple[Candidate, ...]:
        if k < 0:
            raise ValueError("k는 0 이상이어야 합니다.")
        return self.candidates[:k]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """문항 하나의 검색 결과: 보기 1~5 순서의 보기별 목록 5개."""

    config_name: ConfigName
    options: tuple[OptionResult, ...]

    def __post_init__(self) -> None:
        options = tuple(self.options)
        numbers = [o.query.option_no for o in options]
        if numbers != list(range(1, OPTION_COUNT + 1)):
            raise ValueError(f"보기 1~{OPTION_COUNT}의 결과가 순서대로 있어야 합니다: {numbers}")
        object.__setattr__(self, "options", options)

    def question_list(self, max_len: int = DEFAULT_QUESTION_LIST_MAX) -> list[Candidate]:
        """문항 목록: 보기 1의 1위, 보기 2의 1위, …, 보기 1의 2위 … 순으로 합치고 같은 청크는
        처음 나온 것만 남긴다(ADR-011). Hit@5는 이 목록의 상위 5개로 계산한다.
        """
        if max_len < 0:
            raise ValueError("max_len은 0 이상이어야 합니다.")
        merged: list[Candidate] = []
        seen: set[str] = set()
        depth = max((len(o.candidates) for o in self.options), default=0)
        for rank in range(depth):
            for option in self.options:
                if rank >= len(option.candidates):
                    continue
                candidate = option.candidates[rank]
                if candidate.chunk_id in seen:
                    continue
                seen.add(candidate.chunk_id)
                merged.append(candidate)
                if len(merged) == max_len:
                    return merged
        return merged

    def context(self, k_opt: int) -> list[Candidate]:
        """생성 컨텍스트: 보기 1→5 순서로 보기별 상위 `k_opt`개의 합집합(같은 청크는 한 번)."""
        merged: list[Candidate] = []
        seen: set[str] = set()
        for option in self.options:
            for candidate in option.top(k_opt):
                if candidate.chunk_id not in seen:
                    seen.add(candidate.chunk_id)
                    merged.append(candidate)
        return merged

"""채점·지표 (04-interfaces-api §1.5, REQ-071~075).

이 티켓(TKT-BE-M1-03)은 `Grade`와 Hit@5 계산까지 만든다. 전체 지표 `Metrics.compute`는 TKT-BE-M4-02.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from lawqa.evaluation.domain.errors import InvalidEvalDataError
from lawqa.evaluation.domain.models import EvalQuestion
from lawqa.evaluation.domain.run import RunRecord, RunStatus

HIT_K = 5


class FailureCategory(StrEnum):
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    RANKING_MISS = "RANKING_MISS"
    GENERATION_ERROR = "GENERATION_ERROR"
    WRONG_CITATION = "WRONG_CITATION"
    ABSTAIN_FAILURE = "ABSTAIN_FAILURE"


@dataclass(frozen=True, slots=True)
class Grade:
    """기록 1건의 판정. LLM 판정과 사람 판정을 따로 저장한다(D-006)."""

    run_id: str
    question_id: str
    grader: Literal["LLM", "HUMAN"]
    hit_at_5: int | None
    answer_correct: int | None
    citation_valid: int | None
    abstain_correct: int | None
    rationale: str = ""
    judge_prompt_sha: str | None = None
    # CR-014: 두 번째 지표. 번호도 맞고 근거도 충족한 경우에만 1.
    # `answer_correct`(번호만 맞으면 1)와 짝을 이뤄 "풀이 능력"과 "근거 능력"을 나눠 본다.
    # 기존 위치 인자 순서를 지키려고 맨 뒤에 둔다.
    confident_correct: int | None = None

    def __post_init__(self) -> None:
        if self.grader not in ("LLM", "HUMAN"):
            raise InvalidEvalDataError(f"grader는 LLM 또는 HUMAN이어야 합니다: {self.grader}")
        for name in (
            "hit_at_5",
            "answer_correct",
            "citation_valid",
            "abstain_correct",
            "confident_correct",
        ):
            if getattr(self, name) not in (None, 0, 1):
                raise InvalidEvalDataError(f"{name}는 0·1·없음 중 하나여야 합니다.")
        if self.confident_correct == 1 and self.answer_correct == 0:
            raise InvalidEvalDataError(
                "confident_correct=1이면 answer_correct도 1이어야 합니다(CR-014)."
            )
        if self.grader == "LLM" and not self.judge_prompt_sha:
            raise InvalidEvalDataError("LLM 판정에는 judge_prompt_sha가 필요합니다.")


def hit_at_5(record: RunRecord, question: EvalQuestion) -> int:
    """문항 목록 상위 5개에 허용 근거 청크가 하나라도 있으면 1(REQ-071).

    검색 실패(상태가 OK가 아님)는 0, 결과가 5개 미만이면 있는 결과만 본다.
    답변 가능 문항에만 쓴다.
    """
    if not question.answerable:
        raise InvalidEvalDataError(
            f"{question.question_id}: 근거 없음 문항에는 Hit@5를 쓰지 않습니다."
        )
    if record.status is not RunStatus.OK:
        return 0
    allowed = {e.chunk_id for e in question.allowed_evidence}
    return int(any(chunk_id in allowed for chunk_id in record.question_list[:HIT_K]))


def hit_at_5_total(
    records: Iterable[RunRecord], questions: Mapping[str, EvalQuestion]
) -> tuple[int, int]:
    """본 평가 기록의 Hit@5 합계와 분모(답변 가능 문항 수, 17)."""
    hits = 0
    denominator = 0
    for record in records:
        if not record.counts_in_main_metrics:
            continue
        question = questions[record.question_id]
        if not question.answerable:
            continue
        denominator += 1
        hits += hit_at_5(record, question)
    return hits, denominator


@dataclass(frozen=True, slots=True)
class MetricsRow:
    """구성 하나의 지표(04-interfaces-api §1.5). 값은 TKT-BE-M4-02에서 채운다."""

    config_name: str
    hit_at_5: tuple[int, int]
    answer_correct: tuple[int, int]
    citation_valid: tuple[int, int]
    abstain_correct: tuple[int, int]
    call_success: tuple[int, int]
    latency_mean_ms: float | None
    latency_median_ms: float | None
    latency_n: int
    errors: int
    timeouts: int


class Metrics:
    @staticmethod
    def compute(
        records: Sequence[RunRecord],
        grades: Mapping[str, Grade],
        questions: Mapping[str, EvalQuestion],
    ) -> MetricsRow:
        """전체 지표 계산 — TKT-BE-M4-02에서 구현한다(임시)."""
        raise NotImplementedError("Metrics.compute는 TKT-BE-M4-02에서 구현합니다.")

"""answering 도메인 (04-interfaces-api §1.4·§4·§9.1, ADR-004, ADR-013). 표준 라이브러리만 사용.

`Answer`는 결과 종류가 정확히 하나인 최종 결과다(INV-03). 모델 출력은
`Answer.from_model_output`만 거쳐 `Answer`가 된다: ① 형식 ② 후보 밖 인용 제거(INV-01)
③ 근거 부족 판정(INV-13, R-2) ④ 답변.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lawqa.answering.domain.errors import ModelOutputFormatError

OPTION_NOS = (1, 2, 3, 4, 5)
ANSWERED_MESSAGE = "근거를 바탕으로 답했습니다"
# CR-014: 기권(번호 미제시)을 없앴다. 근거가 모자라도 번호는 내고 추정임을 알린다.
UNCERTAIN_MESSAGE = "근거가 부족해 추정한 답입니다"


class Outcome(StrEnum):
    ANSWERED = "ANSWERED"
    INPUT_ERROR = "INPUT_ERROR"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    MODEL_ERROR = "MODEL_ERROR"

    @property
    def is_error(self) -> bool:
        return self in _ERROR_CODES


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    INDEX_NOT_READY = "INDEX_NOT_READY"
    RERANKER_FAILED = "RERANKER_FAILED"
    MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    UNEXPECTED = "UNEXPECTED"


# §4 표: 결과 종류별로 쓸 수 있는 오류 코드
_ERROR_CODES: dict[Outcome, frozenset[ErrorCode]] = {
    Outcome.INPUT_ERROR: frozenset({ErrorCode.INVALID_INPUT}),
    Outcome.RETRIEVAL_ERROR: frozenset(
        {ErrorCode.RETRIEVAL_FAILED, ErrorCode.INDEX_NOT_READY, ErrorCode.RERANKER_FAILED}
    ),
    Outcome.MODEL_ERROR: frozenset(
        {
            ErrorCode.MODEL_CALL_FAILED,
            ErrorCode.MODEL_TIMEOUT,
            ErrorCode.MODEL_OUTPUT_INVALID,
            ErrorCode.UNEXPECTED,
        }
    ),
}


class Verdict(StrEnum):
    """보기 판단. 값은 모델 출력 스키마의 낱말(§5.1)."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: str
    location: str


@dataclass(frozen=True, slots=True)
class OptionJudgment:
    option_no: int
    verdict: Verdict
    reason: str
    citations: tuple[Citation, ...] = ()

    def __post_init__(self) -> None:
        if self.option_no not in OPTION_NOS:
            raise ValueError(f"option_no는 1..5이어야 합니다: {self.option_no}")


@dataclass(frozen=True, slots=True)
class ModelOption:
    no: int
    verdict: str
    reason: str
    citations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    """모델 구조화 출력 그대로(§5.1 스키마). 검증은 `Answer.from_model_output`이 한다."""

    answer: int | None
    sufficient: bool
    options: tuple[ModelOption, ...]
    raw_output: str = field(default="", compare=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], raw_output: str = "") -> ModelAnswer:
        """JSON 객체 → `ModelAnswer`. 타입이 틀리면 `ModelOutputFormatError`."""
        try:
            answer = data["answer"]
            sufficient = data["sufficient"]
            options = data["options"]
            if answer is not None and (isinstance(answer, bool) or not isinstance(answer, int)):
                raise TypeError("answer")
            if not isinstance(sufficient, bool) or not isinstance(options, list):
                raise TypeError("sufficient/options")
            parsed = tuple(
                ModelOption(
                    no=_int(o["no"]),
                    verdict=_str(o["verdict"]),
                    reason=_str(o.get("reason", "")),
                    citations=tuple(_str(c) for c in _list(o.get("citations", []))),
                )
                for o in options
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ModelOutputFormatError(f"모델 출력 형식 오류: {exc!r}") from exc
        return cls(answer=answer, sufficient=sufficient, options=parsed, raw_output=raw_output)


@dataclass(frozen=True, slots=True)
class Answer:
    """답변 결과(INV-01·03·13, CR-014·016).

    `ANSWERED`이면 번호 1..5를 **항상** 낸다. 근거가 충분했는지는 `evidence_sufficient`로
    따로 남긴다 — 두 지표("번호만 맞춘 정답"과 "근거까지 갖춘 정답")를 분리해 재기 위해서다.
    """

    outcome: Outcome
    answer_no: int | None
    judgments: tuple[OptionJudgment, ...]
    error_code: ErrorCode | None
    user_message: str
    dropped_citations: int = 0
    evidence_sufficient: bool = False

    def __post_init__(self) -> None:
        if not self.user_message:
            raise ValueError("user_message가 비어 있습니다.")
        if self.outcome is Outcome.ANSWERED:
            if self.answer_no not in OPTION_NOS:
                raise ValueError("ANSWERED이면 answer_no가 1..5여야 합니다(INV-13).")
            if self.error_code is not None:
                raise ValueError("ANSWERED에는 error_code가 없습니다.")
            if self.evidence_sufficient:
                chosen = [j for j in self.judgments if j.option_no == self.answer_no]
                if not chosen or not chosen[0].citations:
                    raise ValueError(
                        "근거 충족이면 고른 보기의 인용이 1개 이상이어야 합니다(INV-13)."
                    )
        else:
            if self.evidence_sufficient:
                raise ValueError("오류 결과는 근거 충족일 수 없습니다(INV-03).")
            if self.answer_no is not None:
                raise ValueError("오류 결과에는 번호가 없습니다(INV-03).")
            if self.error_code not in _ERROR_CODES[self.outcome]:
                raise ValueError(f"{self.outcome}에 쓸 수 없는 오류 코드: {self.error_code}")
            if self.judgments:
                raise ValueError("오류 결과에는 보기 판단이 없습니다.")

    @classmethod
    def error(cls, outcome: Outcome, code: ErrorCode, message: str) -> Answer:
        """오류 결과(§4). `message`는 화면 문구이며 예외 원문을 넣지 않는다."""
        if not outcome.is_error:
            raise ValueError(f"오류 결과 종류가 아닙니다: {outcome}")
        return cls(
            outcome=outcome, answer_no=None, judgments=(), error_code=code, user_message=message
        )

    @classmethod
    def from_model_output(
        cls,
        output: ModelAnswer,
        candidate_ids: Set[str],
        locations: Mapping[str, str],
    ) -> Answer:
        """ADR-013 검증 순서. 형식이 틀리면 `ModelOutputFormatError`(서비스가 MODEL_ERROR로)."""
        # ① 형식: 보기 1~5 각 1개, 판단 낱말, 번호 범위
        nos = sorted(o.no for o in output.options)
        if nos != list(OPTION_NOS):
            raise ModelOutputFormatError(f"보기 판단은 1~5 각 1개여야 합니다: {nos}")
        if output.answer is not None and output.answer not in OPTION_NOS:
            raise ModelOutputFormatError(f"answer는 1..5 또는 null이어야 합니다: {output.answer}")
        try:
            verdicts = {o.no: Verdict(o.verdict.strip().lower()) for o in output.options}
        except ValueError as exc:
            raise ModelOutputFormatError(f"알 수 없는 판단: {exc}") from exc

        # ② 후보 밖 인용 제거(INV-01), 같은 인용 중복 제거
        dropped = 0
        judgments: list[OptionJudgment] = []
        for option in sorted(output.options, key=lambda o: o.no):
            kept = _unique(c for c in option.citations if c in candidate_ids)
            dropped += sum(1 for c in option.citations if c not in candidate_ids)
            judgments.append(
                OptionJudgment(
                    option_no=option.no,
                    verdict=verdicts[option.no],
                    reason=option.reason,
                    citations=tuple(Citation(c, locations.get(c, c)) for c in kept),
                )
            )

        # ③ 번호 확정(CR-014): 모델이 null을 내도 보기 판단에서 끌어내 **항상** 번호를 낸다
        answer_no = output.answer if output.answer is not None else _fallback_answer_no(judgments)
        chosen = judgments[answer_no - 1]

        # ④ 근거 충족 판정(INV-13, R-2): 번호는 그대로 두고 충족 여부만 기록한다
        sufficient = (
            output.sufficient
            and output.answer is not None
            and chosen.verdict is not Verdict.INSUFFICIENT
            and bool(chosen.citations)
        )
        return cls(
            outcome=Outcome.ANSWERED,
            answer_no=answer_no,
            judgments=tuple(judgments),
            error_code=None,
            user_message=(
                f"정답: {answer_no}번"
                if sufficient
                else f"추정: {answer_no}번 — {UNCERTAIN_MESSAGE}"
            ),
            dropped_citations=dropped,
            evidence_sufficient=sufficient,
        )


def _fallback_answer_no(judgments: list[OptionJudgment]) -> int:
    """모델이 `answer=null`을 냈을 때 쓸 번호(CR-014: 기권하지 않는다).

    옳다고 본 보기가 있으면 그중 가장 작은 번호, 없으면 틀렸다고 단정하지 않은 보기,
    그것도 없으면 1번. 어느 경우든 `evidence_sufficient=false`로 남는다.
    """
    for wanted in (Verdict.CORRECT, Verdict.INSUFFICIENT):
        picked = [j.option_no for j in judgments if j.verdict is wanted]
        if picked:
            return min(picked)
    return OPTION_NOS[0]


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"정수가 아님: {value!r}")
    return value


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"문자열이 아님: {value!r}")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"목록이 아님: {value!r}")
    return value

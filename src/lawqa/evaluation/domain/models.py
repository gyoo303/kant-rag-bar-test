"""평가셋·성공 기준·고정 기록 (04-interfaces-api §1.5, 03-db-schema §5, ADR-014).

표준 라이브러리와 `lawqa.shared.versioning`만 쓴다. 파일 읽기는 저장소
(`evaluation.infrastructure`)가 하고, 이 모듈의 `from_dict`/`to_dict`로 도메인 객체와 주고받는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lawqa.evaluation.domain.errors import FROZEN_MISMATCH, InvalidEvalDataError, RuleViolationError
from lawqa.shared.versioning import sha256_of

OPTION_COUNT = 5
_SOURCE_PATTERN = re.compile(r"^(exam:2026:\d{1,2}|authored)$")
_ANSWER_SOURCE_PATTERN = re.compile(r"^(exam_key:DOC-05|human:.+)$")


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"

    @property
    def id_prefix(self) -> str:
        return "DEV-" if self is Split.DEV else "TEST-"


class QuestionType(StrEnum):
    DIRECT = "direct"
    PARAPHRASE = "paraphrase"
    NO_EVIDENCE = "no_evidence"


# INV-12: 평가셋 구성 (REQ-041~043)
EXPECTED_COMPOSITION: dict[Split, dict[str, int]] = {
    Split.DEV: {"answerable": 8, QuestionType.NO_EVIDENCE.value: 2},
    Split.TEST: {
        QuestionType.DIRECT.value: 10,
        QuestionType.PARAPHRASE.value: 7,
        QuestionType.NO_EVIDENCE.value: 3,
    },
}


@dataclass(frozen=True, slots=True)
class QuestionItem:
    """평가 문항의 입력(지문 + 보기 5개)."""

    stem: str
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.stem.strip():
            raise InvalidEvalDataError("item.stem이 비어 있습니다.")
        if len(self.options) != OPTION_COUNT or not all(o.strip() for o in self.options):
            raise InvalidEvalDataError(
                f"item.options는 비어 있지 않은 보기 {OPTION_COUNT}개여야 합니다."
            )


@dataclass(frozen=True, slots=True)
class ExpectedAnswer:
    answer: int | None
    key_facts: tuple[str, ...]
    insufficient: bool


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    chunk_id: str
    doc_id: str
    location: str

    def __post_init__(self) -> None:
        if not (self.chunk_id and self.doc_id and self.location):
            raise InvalidEvalDataError(
                "allowed_evidence의 chunk_id·doc_id·location은 비울 수 없습니다."
            )


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question_id: str
    type: QuestionType
    source: str
    item: QuestionItem
    expected: ExpectedAnswer
    allowed_evidence: tuple[EvidenceRef, ...]
    answer_source: str
    absence_reason: str | None = None

    def __post_init__(self) -> None:
        qid = self.question_id
        if not _SOURCE_PATTERN.match(self.source):
            raise InvalidEvalDataError(
                f"{qid}: source는 exam:2026:<문번> 또는 authored여야 합니다."
            )
        if not _ANSWER_SOURCE_PATTERN.match(self.answer_source):
            raise InvalidEvalDataError(
                f"{qid}: answer_source는 exam_key:DOC-05 또는 human:<근거>여야 합니다."
            )
        if self.type is QuestionType.NO_EVIDENCE:
            self._check_no_evidence()
        else:
            self._check_answerable()

    @property
    def answerable(self) -> bool:
        return self.type is not QuestionType.NO_EVIDENCE

    def _check_no_evidence(self) -> None:
        qid = self.question_id
        if self.expected.answer is not None or not self.expected.insufficient:
            raise InvalidEvalDataError(
                f"{qid}: 근거 없음 문항은 expected.answer=null, insufficient=true여야 합니다."
            )
        if self.allowed_evidence:
            raise InvalidEvalDataError(f"{qid}: 근거 없음 문항은 allowed_evidence가 비어야 합니다.")
        if not (self.absence_reason and self.absence_reason.strip()):
            raise InvalidEvalDataError(f"{qid}: 근거 없음 문항은 absence_reason이 필요합니다.")

    def _check_answerable(self) -> None:
        qid = self.question_id
        if self.expected.answer is None or not 1 <= self.expected.answer <= OPTION_COUNT:
            raise InvalidEvalDataError(f"{qid}: expected.answer는 1~{OPTION_COUNT}여야 합니다.")
        if self.expected.insufficient:
            raise InvalidEvalDataError(f"{qid}: 답변 가능 문항은 insufficient=false여야 합니다.")
        if not any(f.strip() for f in self.expected.key_facts):
            raise InvalidEvalDataError(f"{qid}: expected.key_facts가 1개 이상 필요합니다.")
        if not self.allowed_evidence:
            raise InvalidEvalDataError(f"{qid}: allowed_evidence가 1개 이상 필요합니다.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvalQuestion:
        """03-db-schema §5 형식의 dict에서 만든다. 필드가 없으면 `InvalidEvalDataError`."""
        qid = str(data.get("question_id", "?"))
        try:
            item = data["item"]
            expected = data["expected"]
            return cls(
                question_id=qid,
                type=QuestionType(data["type"]),
                source=str(data["source"]),
                item=QuestionItem(stem=str(item["stem"]), options=tuple(item["options"])),
                expected=ExpectedAnswer(
                    answer=expected["answer"],
                    key_facts=tuple(expected.get("key_facts", ())),
                    insufficient=bool(expected["insufficient"]),
                ),
                allowed_evidence=tuple(
                    EvidenceRef(e["chunk_id"], e["doc_id"], e["location"])
                    for e in data.get("allowed_evidence", [])
                ),
                answer_source=str(data["answer_source"]),
                absence_reason=data.get("absence_reason"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InvalidEvalDataError):
                raise
            raise InvalidEvalDataError(f"{qid}: 형식 오류 ({type(exc).__name__}: {exc})") from exc

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "question_id": self.question_id,
            "type": self.type.value,
            "source": self.source,
            "item": {"stem": self.item.stem, "options": list(self.item.options)},
            "expected": {
                "answer": self.expected.answer,
                "key_facts": list(self.expected.key_facts),
                "insufficient": self.expected.insufficient,
            },
            "allowed_evidence": [
                {"chunk_id": e.chunk_id, "doc_id": e.doc_id, "location": e.location}
                for e in self.allowed_evidence
            ],
            "answer_source": self.answer_source,
        }
        if self.absence_reason is not None:
            data["absence_reason"] = self.absence_reason
        return data


@dataclass(frozen=True, slots=True)
class EvalSet:
    """평가셋 한 판본(INV-12).

    DEV 10(답변 가능 8·근거 없음 2), TEST 20(직접 10·변형 7·근거 없음 3).
    """

    split: Split
    version: str
    questions: tuple[EvalQuestion, ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise InvalidEvalDataError("평가셋 version이 비어 있습니다.")
        id_pattern = re.compile(rf"^{re.escape(self.split.id_prefix)}\d{{2}}$")
        ids = [q.question_id for q in self.questions]
        bad = [qid for qid in ids if not id_pattern.match(qid)]
        if bad:
            raise InvalidEvalDataError(
                f"{self.split.value} 질문 ID는 {self.split.id_prefix}NN 형식이어야 합니다: {bad}"
            )
        if len(set(ids)) != len(ids):
            raise InvalidEvalDataError(f"{self.split.value} 질문 ID가 중복됩니다.")
        actual = _composition(self.split, self.questions)
        expected = EXPECTED_COMPOSITION[self.split]
        if actual != expected:
            raise InvalidEvalDataError(
                f"{self.split.value} 평가셋 구성이 다릅니다(INV-12). 기대 {expected}, 실제 {actual}"
            )

    @property
    def answerable_count(self) -> int:
        return sum(1 for q in self.questions if q.answerable)

    def get(self, question_id: str) -> EvalQuestion:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        raise KeyError(question_id)

    def sha(self) -> str:
        return sha256_of(_canonical_json(self.to_dict()))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvalSet:
        try:
            split = Split(data["split"])
            questions = tuple(EvalQuestion.from_dict(q) for q in data["questions"])
            return cls(split=split, version=str(data["version"]), questions=questions)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InvalidEvalDataError):
                raise
            raise InvalidEvalDataError(f"평가셋 형식 오류 ({type(exc).__name__}: {exc})") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "split": self.split.value,
            "questions": [q.to_dict() for q in self.questions],
        }


def _composition(split: Split, questions: tuple[EvalQuestion, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        if split is Split.DEV and question.answerable:
            key = "answerable"
        else:
            key = question.type.value
        counts[key] = counts.get(key, 0) + 1
    return counts


# 성공 기준 (D-007, REQ-037)
PRIORITIES = frozenset({"quality", "latency", "cost"})
TARGET_LIMITS: dict[str, tuple[float, float]] = {
    "hit_at_5": (0, 17),
    "answer_correct": (0, 17),
    "citation_valid": (0, 17),
    "abstain_correct": (0, 3),
    "latency_median_s": (0, float("inf")),
    "call_success_rate": (0, 1),
}


@dataclass(frozen=True, slots=True)
class SuccessCriteria:
    """우선순위 3개와 목표 6개. 결과를 보기 전에 고정한다(US-02)."""

    priority: tuple[str, ...]
    targets: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.priority) != 3 or set(self.priority) != PRIORITIES:
            raise InvalidEvalDataError(f"priority는 {sorted(PRIORITIES)}를 한 번씩 담아야 합니다.")
        if set(self.targets) != set(TARGET_LIMITS):
            raise InvalidEvalDataError(f"targets 키는 {sorted(TARGET_LIMITS)}여야 합니다.")
        for key, value in self.targets.items():
            low, high = TARGET_LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InvalidEvalDataError(f"targets.{key}는 숫자여야 합니다.")
            if not low <= value <= high or (key == "latency_median_s" and value <= 0):
                raise InvalidEvalDataError(f"targets.{key} 값 {value}가 범위를 벗어났습니다.")

    def sha(self) -> str:
        return sha256_of(_canonical_json(self.to_dict()))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SuccessCriteria:
        try:
            return cls(priority=tuple(data["priority"]), targets=dict(data["targets"]))
        except (KeyError, TypeError) as exc:
            raise InvalidEvalDataError(f"성공 기준 형식 오류 ({exc})") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"priority": list(self.priority), "targets": dict(self.targets)}


class FreezeStage(StrEnum):
    CRITERIA = "criteria"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class FreezeRecord:
    """고정 기록(ADR-014, AQ-012). `criteria` 단계는 성공 기준 해시만, `final`은 전부.

    `verify`는 `git_commit`·`frozen_at`을 비교하지 않는다(고정 뒤 결과 커밋은 정상).
    """

    stage: FreezeStage
    success_criteria_sha: str
    evalset_sha: str | None = None
    config_sha: Mapping[str, str] = field(default_factory=dict)
    prompt_sha: str | None = None
    index_version: str | None = None
    git_commit: str | None = None
    frozen_at: str | None = None

    def __post_init__(self) -> None:
        if not self.success_criteria_sha:
            raise InvalidEvalDataError("success_criteria_sha가 비어 있습니다.")
        if self.stage is FreezeStage.FINAL and not (
            self.evalset_sha and self.config_sha and self.prompt_sha and self.index_version
        ):
            raise InvalidEvalDataError(
                "final 고정에는 evalset_sha·config_sha·prompt_sha·index_version이 모두 필요합니다."
            )

    def compared_fields(self) -> dict[str, Any]:
        return {
            "success_criteria_sha": self.success_criteria_sha,
            "evalset_sha": self.evalset_sha,
            "config_sha": dict(self.config_sha),
            "prompt_sha": self.prompt_sha,
            "index_version": self.index_version,
        }

    def verify(self, current: FreezeRecord) -> None:
        """현재 값이 고정 기록과 같은지 확인한다(INV-06). 다르면 `RuleViolationError`."""
        frozen = self.compared_fields()
        now = current.compared_fields()
        if self.stage is FreezeStage.CRITERIA:
            frozen = {"success_criteria_sha": frozen["success_criteria_sha"]}
            now = {"success_criteria_sha": now["success_criteria_sha"]}
        diff = sorted(key for key in frozen if frozen[key] != now[key])
        if diff:
            raise RuleViolationError(FROZEN_MISMATCH, f"고정 이후 바뀐 항목: {', '.join(diff)}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FreezeRecord:
        try:
            return cls(
                stage=FreezeStage(data["stage"]),
                success_criteria_sha=str(data["success_criteria_sha"]),
                evalset_sha=data.get("evalset_sha"),
                config_sha=dict(data.get("config_sha") or {}),
                prompt_sha=data.get("prompt_sha"),
                index_version=data.get("index_version"),
                git_commit=data.get("git_commit"),
                frozen_at=data.get("frozen_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InvalidEvalDataError):
                raise
            raise InvalidEvalDataError(f"고정 기록 형식 오류 ({exc})") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            **self.compared_fields(),
            "git_commit": self.git_commit,
            "frozen_at": self.frozen_at,
        }


def _canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

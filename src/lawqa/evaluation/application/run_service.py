"""평가 실행 `eval run` (04-interfaces-api §2·SEQ-04, ADR-014, R-1, INV-05·06·07·11).

순서: 평가셋 → 대상 문항(`--only`, 재시도면 원 실행의 오류 건) → 실행 허용 검사(본 평가·재시도는
최종 고정과 현재 값 비교) → (`--dry-run`이면 여기서 끝) → `run.json` 생성 또는 이어 하기 →
문항마다 답변 → 기록 한 줄을 바로 디스크에 씀. 중간에 멈춰도 쓴 줄은 남고 `--resume`으로 이어 한다.
기록은 지우거나 덮어쓰지 않는다(재시도는 별도 실행, R-1).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from lawqa.answering.application.answer_service import AnswerEnvelope
from lawqa.evaluation.domain.errors import (
    FROZEN_MISMATCH,
    INVALID_RUN_KIND,
    InvalidEvalDataError,
    RuleViolationError,
)
from lawqa.evaluation.domain.models import EvalQuestion, FreezeRecord, FreezeStage, Split
from lawqa.evaluation.domain.ports import EvalSetRepository, FreezeStore
from lawqa.evaluation.domain.run import ALLOWED_KINDS, Run, RunKind, RunRecord, RunStatus
from lawqa.shared.clock import Clock
from lawqa.shared.logging_setup import log_event

log = logging.getLogger(__name__)

_ERROR_OUTCOMES = {"RETRIEVAL_ERROR", "MODEL_ERROR"}


class Answerer(Protocol):
    def answer(self, item_input: Mapping[str, Any], config_name: str) -> AnswerEnvelope: ...


class RunRecordStore(Protocol):
    def exists(self, run_id: str) -> bool: ...
    def create(self, run: Run) -> None: ...
    def append(self, record: RunRecord) -> None: ...
    def load(self, run_id: str) -> tuple[Run, list[RunRecord]]: ...


@dataclass(frozen=True, slots=True)
class RunPlan:
    """실행 전 검사 결과(`--dry-run` 출력)."""

    run_id: str
    question_ids: tuple[str, ...]
    already_done: tuple[str, ...] = ()
    resumed: bool = False


@dataclass(slots=True)
class RunSummary:
    plan: RunPlan
    outcomes: dict[str, int] = field(default_factory=dict)

    @property
    def recorded(self) -> int:
        return sum(self.outcomes.values())


class EvalRunService:
    def __init__(
        self,
        *,
        evalsets: EvalSetRepository,
        freeze_store: FreezeStore,
        current_freeze: Callable[[], FreezeRecord],
        store: RunRecordStore,
        versions_for: Callable[[str], Mapping[str, str]],
        answerer: Callable[[], Answerer],
        clock: Clock,
    ) -> None:
        """`answerer`·`versions_for`·`current_freeze`는 필요할 때만 부른다(검사에 걸리면 모델을
        적재하지 않음)."""
        self._evalsets = evalsets
        self._freeze_store = freeze_store
        self._current_freeze = current_freeze
        self._store = store
        self._versions_for = versions_for
        self._answerer = answerer
        self._clock = clock

    # ── 실행 전 검사 ──
    def plan(
        self,
        split: Split,
        config_name: str,
        kind: RunKind,
        *,
        retry_of: str | None = None,
        resume_run_id: str | None = None,
        only: Sequence[str] | None = None,
    ) -> RunPlan:
        frozen = self._freeze_store.load()
        # 현재 값(평가셋·성공 기준·색인 판본)은 분할·종류·고정 기록 검사를 통과할 때만 계산:
        # 규칙 위반이면 입력 파일이 없어도 규칙 위반(종료 3)으로 먼저 알린다.
        needs_current = (
            kind in (RunKind.MAIN, RunKind.RETRY)
            and kind in ALLOWED_KINDS[split]
            and frozen is not None
            and frozen.stage is FreezeStage.FINAL
        )
        current = self._current_freeze() if needs_current else None
        Run.check_allowed(kind, split, frozen, current, retry_of)

        evalset = self._evalsets.load(split)
        questions = _select(evalset.questions, only)
        if kind is RunKind.RETRY and retry_of:
            questions = self._retry_targets(retry_of, split, config_name, questions, only)

        if resume_run_id:
            run, records = self._resumable(resume_run_id, split, config_name, kind, retry_of)
            done = {r.question_id for r in records}
            return RunPlan(
                run_id=run.run_id,
                question_ids=tuple(q.question_id for q in questions if q.question_id not in done),
                already_done=tuple(sorted(done)),
                resumed=True,
            )
        run_id = Run.make_id(self._clock.now(), config_name, kind)
        return RunPlan(run_id=run_id, question_ids=tuple(q.question_id for q in questions))

    # ── 실행 ──
    def run(
        self,
        split: Split,
        config_name: str,
        kind: RunKind,
        *,
        retry_of: str | None = None,
        resume_run_id: str | None = None,
        only: Sequence[str] | None = None,
    ) -> RunSummary:
        plan = self.plan(
            split, config_name, kind, retry_of=retry_of, resume_run_id=resume_run_id, only=only
        )
        versions = dict(self._versions_for(config_name))
        if plan.resumed:
            run, _ = self._store.load(plan.run_id)
            if dict(run.versions) != versions:
                changed = sorted(k for k in versions if run.versions.get(k) != versions[k])
                raise RuleViolationError(
                    FROZEN_MISMATCH,
                    f"이어 할 수 없음, {run.run_id} 뒤 바뀐 버전: {', '.join(changed)}"
                    " (바뀐 설정은 새 실행으로)",
                )
        else:
            run = Run(
                run_id=plan.run_id,
                kind=kind,
                split=split,
                config_name=config_name,
                versions=versions,
                started_at=self._clock.now(),
                retry_of=retry_of,
            )
            self._store.create(run)  # 이미 있으면 FileExistsError(덮어쓰지 않음)

        summary = RunSummary(plan=plan)
        if not plan.question_ids:
            return summary
        answerer = self._answerer()
        evalset = self._evalsets.load(split)
        for question_id in plan.question_ids:
            question = evalset.get(question_id)
            started_at = self._clock.now().isoformat(timespec="seconds")
            envelope = answerer.answer(
                {"stem": question.item.stem, "options": list(question.item.options)}, config_name
            )
            record = build_record(run, question_id, started_at, envelope)
            self._store.append(record)
            summary.outcomes[record.outcome] = summary.outcomes.get(record.outcome, 0) + 1
            log_event(
                log,
                "eval_record",
                run_id=run.run_id,
                question_id=question_id,
                status=record.status.value,
                outcome=record.outcome,
            )
        return summary

    def _retry_targets(
        self,
        retry_of: str,
        split: Split,
        config_name: str,
        questions: Sequence[EvalQuestion],
        only: Sequence[str] | None,
    ) -> list[EvalQuestion]:
        """재시도 대상: 원 본 평가 실행에서 오류·시간 초과였던 문항(`--only`가 있으면 그 문항)."""
        if not self._store.exists(retry_of):
            raise InvalidEvalDataError(f"재시도할 원 실행이 없습니다: {retry_of}")
        original, records = self._store.load(retry_of)
        if original.kind is not RunKind.MAIN:
            raise RuleViolationError(INVALID_RUN_KIND, f"{retry_of}는 본 평가 실행이 아닙니다.")
        if original.split is not split or original.config_name != config_name:
            raise RuleViolationError(
                INVALID_RUN_KIND,
                f"{retry_of}는 {original.split.value}·구성 {original.config_name} 실행입니다.",
            )
        if only:
            return list(questions)
        failed = {r.question_id for r in records if r.status is not RunStatus.OK}
        return [q for q in questions if q.question_id in failed]

    def _resumable(
        self,
        run_id: str,
        split: Split,
        config_name: str,
        kind: RunKind,
        retry_of: str | None,
    ) -> tuple[Run, list[RunRecord]]:
        if not self._store.exists(run_id):
            raise InvalidEvalDataError(f"이어 할 실행이 없습니다: {run_id}")
        run, records = self._store.load(run_id)
        if (run.split, run.config_name, run.kind, run.retry_of) != (
            split,
            config_name,
            kind,
            retry_of,
        ):
            raise InvalidEvalDataError(
                f"{run_id}는 {run.split.value}·{run.config_name}·{run.kind.value} 실행입니다. "
                "--split·--config·--kind·--retry-of를 원 실행과 같게 주세요."
            )
        return run, records


def build_record(run: Run, question_id: str, started_at: str, env: AnswerEnvelope) -> RunRecord:
    """답변 봉투 → 실행 기록 한 줄(03-db-schema §5 필드, AC-13-2)."""
    data = env.to_dict()
    answer = env.answer
    status = _status(answer.outcome.value, data["error_code"])
    retrieval = data["retrieval"]
    citations: list[dict[str, str]] = []
    for judgment in data["judgments"]:
        for citation in judgment["citations"]:
            if citation not in citations:
                citations.append(citation)
    return RunRecord(
        run_id=run.run_id,
        kind=run.kind,
        split=run.split,
        config_name=run.config_name,
        versions=run.versions,
        question_id=question_id,
        attempt=2 if run.kind is RunKind.RETRY else 1,
        started_at=started_at,
        latency_ms={
            "total": env.latency_ms,
            "rewrite": None,  # 리라이트·재정렬은 검색 시간(retrieval)에 포함
            "retrieval": env.retrieval_ms,
            "rerank": None,
            "generation": env.generation_ms,
        },
        status=status,
        outcome=answer.outcome.value,
        question_list=tuple(retrieval["question_list"]) if retrieval else (),
        error_code=data["error_code"],
        retry_of=run.retry_of,
        details={
            # CR-014: 두 지표를 나중에 계산하려면 근거 충족 여부가 기록에 있어야 한다
            "evidence_sufficient": data["evidence_sufficient"],
            "queries": data["queries"],
            "candidates": (
                {str(o["option_no"]): o["candidates"] for o in retrieval["options"]}
                if retrieval
                else {}
            ),
            "context_chunk_ids": [c["chunk_id"] for c in data["context"]],
            "context": data["context"],
            "context_chars": data["context_chars"],
            "raw_output": data["raw_output"],
            "answer": {
                "answer_no": data["answer_no"],
                "user_message": data["user_message"],
                "judgments": data["judgments"],
                "dropped_citations": data["dropped_citations"],
            },
            "citations": citations,
        },
    )


def _status(outcome: str, error_code: str | None) -> RunStatus:
    if outcome not in _ERROR_OUTCOMES:
        return RunStatus.OK
    return RunStatus.TIMEOUT if error_code == "MODEL_TIMEOUT" else RunStatus.ERROR


def _select(questions: Sequence[EvalQuestion], only: Sequence[str] | None) -> list[EvalQuestion]:
    if not only:
        return list(questions)
    known = {q.question_id for q in questions}
    unknown = [qid for qid in only if qid not in known]
    if unknown:
        raise InvalidEvalDataError(f"평가셋에 없는 질문 ID: {', '.join(unknown)}")
    wanted = set(only)
    return [q for q in questions if q.question_id in wanted]

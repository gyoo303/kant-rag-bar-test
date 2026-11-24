"""실행·실행 기록과 실행 허용 규칙 (04-interfaces-api §1.5, ADR-014, INV-05·06·07·11)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from lawqa.evaluation.domain.errors import (
    FROZEN_MISMATCH,
    INVALID_RUN_KIND,
    TEST_SPLIT_IN_DEV,
    InvalidEvalDataError,
    RuleViolationError,
)
from lawqa.evaluation.domain.models import FreezeRecord, FreezeStage, Split

CONFIG_NAMES = ("A", "B", "C", "C+R")
REQUIRED_VERSION_KEYS = frozenset(
    {
        "corpus",
        "index",
        "config_sha",
        "prompt_sha",
        "gen_model",
        "embedding_model",
        "reranker_model",
    }
)
LATENCY_KEYS = ("total", "rewrite", "retrieval", "rerank", "generation")
_RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-(A|B|C|C\+R)-(main|warmup|retry|extra)$")


class RunKind(StrEnum):
    MAIN = "main"
    WARMUP = "warmup"
    RETRY = "retry"
    EXTRA = "extra"


class RunStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


# 분할별 허용 실행 종류 (INV-05: test는 개발·튜닝에 쓰지 않음, dev는 본 평가가 아님)
ALLOWED_KINDS: dict[Split, frozenset[RunKind]] = {
    Split.DEV: frozenset({RunKind.WARMUP, RunKind.EXTRA}),
    Split.TEST: frozenset({RunKind.MAIN, RunKind.RETRY, RunKind.EXTRA}),
}


@dataclass(frozen=True, slots=True)
class Run:
    """실행 하나(구성 하나 × 분할 하나)."""

    run_id: str
    kind: RunKind
    split: Split
    config_name: str
    versions: Mapping[str, str]
    started_at: datetime
    retry_of: str | None = None

    def __post_init__(self) -> None:
        if not _RUN_ID_PATTERN.match(self.run_id):
            raise InvalidEvalDataError(
                f"run_id 형식은 <YYYYMMDD-HHMMSS>-<구성>-<종류>여야 합니다: {self.run_id}"
            )
        if not self.run_id.endswith(f"-{self.config_name}-{self.kind.value}"):
            raise InvalidEvalDataError(f"run_id가 구성·종류와 다릅니다: {self.run_id}")
        _check_versions(self.versions)
        if (self.kind is RunKind.RETRY) != (self.retry_of is not None):
            raise InvalidEvalDataError("retry_of는 재시도 실행에만, 그리고 반드시 있어야 합니다.")

    @staticmethod
    def make_id(started_at: datetime, config_name: str, kind: RunKind) -> str:
        if config_name not in CONFIG_NAMES:
            raise InvalidEvalDataError(f"알 수 없는 구성: {config_name}")
        return f"{started_at.strftime('%Y%m%d-%H%M%S')}-{config_name}-{kind.value}"

    @staticmethod
    def check_allowed(
        kind: RunKind,
        split: Split,
        freeze: FreezeRecord | None,
        current: FreezeRecord,
        retry_of: str | None = None,
    ) -> None:
        """실행을 시작해도 되는지 검사한다(INV-05·06). 안 되면 `RuleViolationError`.

        - test는 main·retry·extra만, dev는 warmup·extra만
        - main·retry는 final 고정 기록이 있고 현재 값과 같아야 함
        - retry는 retry_of(원 실행 ID)가 있어야 함
        """
        if kind not in ALLOWED_KINDS[split]:
            if split is Split.TEST:
                raise RuleViolationError(
                    TEST_SPLIT_IN_DEV, f"test 문항은 {kind.value} 실행에 쓸 수 없습니다(INV-05)."
                )
            raise RuleViolationError(
                INVALID_RUN_KIND, f"dev 문항은 {kind.value} 실행(본 평가·재시도)에 쓸 수 없습니다."
            )
        if kind is RunKind.RETRY and not retry_of:
            raise RuleViolationError(
                INVALID_RUN_KIND, "재시도 실행에는 --retry-of(원 실행 ID)가 필요합니다."
            )
        if kind in (RunKind.MAIN, RunKind.RETRY):
            if freeze is None or freeze.stage is not FreezeStage.FINAL:
                raise RuleViolationError(
                    FROZEN_MISMATCH,
                    "본 평가 전에 `eval freeze --stage final`로 최종 고정을 해야 합니다(INV-06).",
                )
            freeze.verify(current)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """실행 안의 문항 1건 결과(03-db-schema §5). 검색·답변 상세는 dict로 그대로 담는다."""

    run_id: str
    kind: RunKind
    split: Split
    config_name: str
    versions: Mapping[str, str]
    question_id: str
    attempt: int
    started_at: str
    latency_ms: Mapping[str, int | None]
    status: RunStatus
    outcome: str
    question_list: tuple[str, ...] = ()
    error_code: str | None = None
    retry_of: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_versions(self.versions)
        if self.attempt < 1:
            raise InvalidEvalDataError("attempt는 1 이상이어야 합니다.")
        if (self.kind is RunKind.RETRY) != (self.retry_of is not None):
            raise InvalidEvalDataError("retry_of는 재시도 기록에만, 그리고 반드시 있어야 합니다.")
        if set(self.latency_ms) != set(LATENCY_KEYS):
            raise InvalidEvalDataError(f"latency_ms 키는 {list(LATENCY_KEYS)}여야 합니다.")
        if self.status is not RunStatus.OK and not self.error_code:
            raise InvalidEvalDataError("오류·시간 초과 기록에는 error_code가 필요합니다.")

    @property
    def counts_in_main_metrics(self) -> bool:
        """본 지표에 들어가는 기록인가(R-1: 재시도·워밍업·추가 실험은 제외)."""
        return self.kind is RunKind.MAIN


def _check_versions(versions: Mapping[str, str]) -> None:
    missing = REQUIRED_VERSION_KEYS - set(versions)
    empty = [k for k in REQUIRED_VERSION_KEYS & set(versions) if not versions[k]]
    if missing or empty:
        raise InvalidEvalDataError(
            f"versions에 필수 키가 없거나 비었습니다(INV-11): {sorted(missing) + sorted(empty)}"
        )

"""고정 서비스 `eval freeze` (US-02, US-12, ADR-014, SEQ-06, 04-interfaces-api §9.3).

- `criteria`: 성공 기준 해시만 기록(M1). 같은 해시로 다시 고정하는 것은 허용, 바뀐 기준은 거부.
- `final`: 성공 기준·평가셋·구성별 설정·프롬프트·완료된 색인 판본·git HEAD를 기록(M3).
  작업 트리에 커밋 안 된 변경이 있으면 거부, 이미 final이면 다시 고정하지 않는다.
- git 태그는 사람이 단다(`freeze-criteria`, `freeze-final`).

외부 값(설정 해시·프롬프트 해시·색인 판본·git·시각)은 생성자로 주입받는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal, Protocol

from lawqa.evaluation.domain.errors import FROZEN_MISMATCH, RuleViolationError
from lawqa.evaluation.domain.models import FreezeRecord, FreezeStage, Split
from lawqa.evaluation.domain.ports import EvalSetRepository, FreezeStore, SuccessCriteriaStore
from lawqa.shared.clock import Clock
from lawqa.shared.versioning import sha256_of


class GitInfo(Protocol):
    def head(self) -> str: ...
    def has_uncommitted_changes(self) -> bool: ...


class FreezeService:
    def __init__(
        self,
        *,
        criteria_store: SuccessCriteriaStore,
        evalset_repo: EvalSetRepository,
        freeze_store: FreezeStore,
        config_shas: Callable[[], Mapping[str, str]],
        prompt_sha: Callable[[], str],
        index_version: Callable[[], str],
        git: GitInfo,
        clock: Clock,
    ) -> None:
        self._criteria = criteria_store
        self._evalsets = evalset_repo
        self._freeze = freeze_store
        self._config_shas = config_shas
        self._prompt_sha = prompt_sha
        self._index_version = index_version
        self._git = git
        self._clock = clock

    def freeze(self, kind: Literal["criteria", "final"]) -> FreezeRecord:
        stage = FreezeStage(kind)
        existing = self._freeze.load()
        if existing is not None and existing.stage is FreezeStage.FINAL:
            raise RuleViolationError(
                FROZEN_MISMATCH,
                "이미 final 고정이 있습니다. 덮어쓰지 않습니다(바꾼 실험은 --kind extra).",
            )
        if stage is FreezeStage.FINAL and self._git.has_uncommitted_changes():
            raise RuleViolationError(
                FROZEN_MISMATCH,
                "커밋하지 않은 변경이 있습니다. 모두 커밋한 뒤 final 고정을 하세요.",
            )
        record = self._build(stage)
        if existing is not None:  # criteria 고정이 이미 있음
            existing.verify(record)  # 성공 기준이 바뀌었으면 FROZEN_MISMATCH
            if stage is FreezeStage.CRITERIA:
                return existing  # 같은 기준으로 다시 고정: 처음 고정 시각을 그대로 둔다(AC-02-2)
        self._freeze.save(record)
        return record

    def current(self) -> FreezeRecord:
        """저장하지 않고 지금 값으로 final 기록을 만든다(본 평가 전 `verify`용, SEQ-04)."""
        return self._build(FreezeStage.FINAL)

    def check_frozen_before(self, first_main_run_started_at: datetime) -> None:
        """AC-02-2: 성공 기준 고정이 첫 본 평가 실행보다 앞섰는지 확인한다."""
        record = self._freeze.load()
        if record is None or record.frozen_at is None:
            raise RuleViolationError(FROZEN_MISMATCH, "성공 기준 고정 기록이 없습니다.")
        if datetime.fromisoformat(record.frozen_at) >= first_main_run_started_at:
            raise RuleViolationError(
                FROZEN_MISMATCH,
                f"고정 시각 {record.frozen_at}이 첫 본 평가 실행보다 늦습니다.",
            )

    def _build(self, stage: FreezeStage) -> FreezeRecord:
        criteria_sha = self._criteria.load().sha()
        frozen_at = self._clock.now().isoformat(timespec="seconds")
        git_commit = self._git.head()
        if stage is FreezeStage.CRITERIA:
            return FreezeRecord(
                stage=stage,
                success_criteria_sha=criteria_sha,
                git_commit=git_commit,
                frozen_at=frozen_at,
            )
        dev_sha = self._evalsets.load(Split.DEV).sha()
        test_sha = self._evalsets.load(Split.TEST).sha()
        return FreezeRecord(
            stage=stage,
            success_criteria_sha=criteria_sha,
            evalset_sha=sha256_of(f"dev:{dev_sha}\ntest:{test_sha}".encode()),
            config_sha=dict(self._config_shas()),
            prompt_sha=self._prompt_sha(),
            index_version=self._index_version(),
            git_commit=git_commit,
            frozen_at=frozen_at,
        )

"""evaluation 외부 연결(저장소·모델·파일)과 조립 함수(CONV-03 `build_*`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from lawqa.evaluation.application.freeze_service import FreezeService
from lawqa.evaluation.infrastructure.files import (
    FreezeFile,
    JsonEvalSetRepository,
    SuccessCriteriaFile,
)
from lawqa.evaluation.infrastructure.git_info import SubprocessGitInfo
from lawqa.shared.clock import SystemClock
from lawqa.shared.settings import Settings

FREEZE_FILE = "FREEZE.json"
SUCCESS_CRITERIA_FILE = "success_criteria.json"


def build_freeze_service(
    settings: Settings,
    *,
    config_shas: Callable[[], Mapping[str, str]],
    prompt_sha: Callable[[], str],
    index_version: Callable[[], str],
    repo_dir: Path = Path("."),
) -> FreezeService:
    """`eval freeze`용 서비스. 다른 모듈에 속한 값(프롬프트·색인 판본)은 진입점이 넘긴다."""
    eval_dir = settings.paths.eval_dir
    return FreezeService(
        criteria_store=SuccessCriteriaFile(eval_dir / SUCCESS_CRITERIA_FILE),
        evalset_repo=JsonEvalSetRepository(eval_dir),
        freeze_store=FreezeFile(eval_dir / FREEZE_FILE),
        config_shas=config_shas,
        prompt_sha=prompt_sha,
        index_version=index_version,
        git=SubprocessGitInfo(repo_dir),
        clock=SystemClock(),
    )

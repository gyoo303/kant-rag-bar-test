"""evaluation 외부 연결(저장소·모델·파일)과 조립 함수(CONV-03 `build_*`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from lawqa.evaluation.application.freeze_service import FreezeService
from lawqa.evaluation.application.run_service import Answerer, EvalRunService
from lawqa.evaluation.domain.models import FreezeRecord
from lawqa.evaluation.infrastructure.files import (
    FreezeFile,
    JsonEvalSetRepository,
    RunStore,
    SuccessCriteriaFile,
)
from lawqa.evaluation.infrastructure.git_info import SubprocessGitInfo
from lawqa.shared.clock import SystemClock
from lawqa.shared.settings import Settings

FREEZE_FILE = "FREEZE.json"
SUCCESS_CRITERIA_FILE = "success_criteria.json"


def build_run_service(
    settings: Settings,
    *,
    current_freeze: Callable[[], FreezeRecord],
    versions_for: Callable[[str], Mapping[str, str]],
    answerer: Callable[[], Answerer],
) -> EvalRunService:
    """`eval run`용 서비스. 답변기(answering 조립)는 진입점이 넘긴다."""
    return EvalRunService(
        evalsets=JsonEvalSetRepository(settings.paths.eval_dir),
        freeze_store=FreezeFile(settings.paths.eval_dir / FREEZE_FILE),
        current_freeze=current_freeze,
        store=RunStore(settings.paths.results_dir),
        versions_for=versions_for,
        answerer=answerer,
        clock=SystemClock(),
    )


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

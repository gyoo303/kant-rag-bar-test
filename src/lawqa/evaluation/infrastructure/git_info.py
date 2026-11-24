"""git 상태 읽기 (SEQ-06: 고정 기록의 HEAD, final 고정 전 커밋 안 된 변경 확인)."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    """git 명령 실패(저장소가 아님, git 없음 등)."""


class SubprocessGitInfo:
    """`git` 명령으로 HEAD와 작업 트리 상태를 읽는다."""

    def __init__(self, repo_dir: Path = Path(".")) -> None:
        self._repo_dir = repo_dir

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def has_uncommitted_changes(self) -> bool:
        """추적 중인 파일의 변경만 본다(추적하지 않는 새 파일은 고정 대상이 아니므로 제외)."""
        return bool(self._git("status", "--porcelain", "--untracked-files=no").strip())

    def _git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._repo_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise GitCommandError(f"git {' '.join(args)} 실패: {exc}") from exc
        return result.stdout

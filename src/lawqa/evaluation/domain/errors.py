"""evaluation 도메인 예외 (04-interfaces-api §1.6, §4). 표준 라이브러리만 사용."""

from __future__ import annotations

# 규칙 위반 코드 (04-interfaces-api §4 "거부(규칙 위반)")
TEST_SPLIT_IN_DEV = "TEST_SPLIT_IN_DEV"
FROZEN_MISMATCH = "FROZEN_MISMATCH"
LEAK_DETECTED = "LEAK_DETECTED"
INVALID_RUN_KIND = "INVALID_RUN_KIND"


class InvalidEvalDataError(ValueError):
    """평가셋·성공 기준·실행 기록·채점 값이 형식·규칙에 맞지 않음(입력 오류, 종료 코드 1)."""


class RuleViolationError(Exception):
    """평가 무결성 규칙 위반(명령 종료 코드 3). `code`는 위 상수 중 하나."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

"""answering 도메인 예외 (04-interfaces-api §1.6). infrastructure가 던지고 AnswerService가
`Answer(MODEL_ERROR, ...)`로 바꾼다(ADR-004). 표준 라이브러리만 사용."""

from __future__ import annotations


class ModelCallError(RuntimeError):
    """생성 모델 호출 실패(연결·인증·서버 오류)."""


class ModelTimeoutError(ModelCallError):
    """생성 모델 시간 초과."""


class ModelOutputFormatError(ValueError):
    """모델 출력이 스키마·규칙(보기 1~5 각 1개 등)에 맞지 않음."""

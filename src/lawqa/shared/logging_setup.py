"""로그 설정 (04-interfaces-api §11, CONV-07).

한 줄 형식: `ts level module event key=value ...`. 비밀값·DATABASE_URL은 남기지 않는다.
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: int | str = logging.INFO) -> None:
    """루트 로거를 한 줄 형식으로 설정한다. 여러 번 불러도 핸들러가 늘지 않는다."""
    logging.basicConfig(level=level, format=_FORMAT, force=True)


def format_event(event: str, **fields: object) -> str:
    """`event=<이름> key=value ...` 문자열을 만든다. 값의 공백은 `_`로 바꾼다."""
    parts = [f"event={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={str(value).replace(' ', '_')}")
    return " ".join(parts)


def log_event(
    logger: logging.Logger, event: str, level: int = logging.INFO, **fields: object
) -> None:
    """이벤트 한 줄을 남긴다. 예: `log_event(log, "answer", outcome="ANSWERED", latency_ms=812)`."""
    logger.log(level, format_event(event, **fields))

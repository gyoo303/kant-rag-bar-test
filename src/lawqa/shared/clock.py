"""현재 시각 제공 (04-interfaces-api §1.1, §10).

도메인은 현재 시각을 직접 얻지 않고 인자로 받는다. 응용 서비스가 `Clock`을 주입받아 넘긴다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """시스템 시각(로컬 시간대 포함)."""

    def now(self) -> datetime:
        return datetime.now().astimezone()

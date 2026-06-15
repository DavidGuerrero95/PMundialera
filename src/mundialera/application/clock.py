from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class SystemClock:
    def __init__(self, timezone_name: str) -> None:
        self._timezone = ZoneInfo(timezone_name)

    def now(self) -> datetime:
        return datetime.now(self._timezone)

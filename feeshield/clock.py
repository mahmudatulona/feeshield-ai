from datetime import datetime, timedelta, timezone, date
from typing import Optional


class Clock:
    """Injectable clock so tests (and the demo) are reproducible."""

    def __init__(self, fixed: Optional[datetime] = None, scenario_date: Optional[date] = None):
        self._fixed = fixed
        self._scenario_date = scenario_date

    def now(self) -> datetime:
        return self._fixed or datetime.now(timezone.utc)

    def today(self) -> date:
        return self._scenario_date or self.now().date()

    def advance(self, seconds: float) -> None:
        self._fixed = self.now() + timedelta(seconds=seconds)

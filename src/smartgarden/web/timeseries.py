"""Picking a rollup tier from a requested time range (API-3).

Pure and framework-free on purpose: whether a range is "short" or "long"
enough to warrant downsampling has nothing to do with HTTP, and testing it
should not require spinning up FastAPI.

The boundaries follow the tier purposes docs/architecture.html section 05
already states: raw for "live view, short-window trends"; minute for
"charts beyond a day"; quarter-hour for "season-over-season comparison" --
which is why a 60-day range (about two months) gets quarter-hour rather
than minute, even though minute data is retained for 90 days. Retention and
resolution answer different questions: how long data survives, versus how
much of it is worth handing a chart in one response.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

__all__ = ["MINUTE_MAX", "RAW_MAX", "Tier", "pick_tier"]

Tier = Literal["raw", "minute", "quarter_hour"]

RAW_MAX = timedelta(days=1)
MINUTE_MAX = timedelta(days=30)


def pick_tier(start: datetime, end: datetime) -> Tier:
    span = end - start
    if span <= RAW_MAX:
        return "raw"
    if span <= MINUTE_MAX:
        return "minute"
    return "quarter_hour"

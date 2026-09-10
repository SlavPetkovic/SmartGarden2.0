"""pick_tier: raw/minute/quarter_hour chosen from the requested range
(API-3). Pure -- no FastAPI needed, so this file needs no self-skip."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from smartgarden.web.timeseries import pick_tier

START = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


class TestPickTier(unittest.TestCase):
    def test_one_hour_range_hits_raw(self) -> None:
        # The exact example named in BUILD-PLAN.md's layer 05 gate.
        self.assertEqual(pick_tier(START, START + timedelta(hours=1)), "raw")

    def test_sixty_day_range_hits_quarter_hour(self) -> None:
        # Also named verbatim in the gate.
        self.assertEqual(pick_tier(START, START + timedelta(days=60)), "quarter_hour")

    def test_one_day_is_still_raw(self) -> None:
        self.assertEqual(pick_tier(START, START + timedelta(days=1)), "raw")

    def test_just_over_a_day_is_minute(self) -> None:
        self.assertEqual(pick_tier(START, START + timedelta(days=1, seconds=1)), "minute")

    def test_thirty_days_is_still_minute(self) -> None:
        self.assertEqual(pick_tier(START, START + timedelta(days=30)), "minute")

    def test_just_over_thirty_days_is_quarter_hour(self) -> None:
        self.assertEqual(
            pick_tier(START, START + timedelta(days=30, seconds=1)), "quarter_hour"
        )


if __name__ == "__main__":
    unittest.main()

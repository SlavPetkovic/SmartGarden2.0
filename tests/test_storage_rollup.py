"""Rollups: idempotent, and min/max/mean/count rather than just mean
(STOR-2, STOR-3)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from smartgarden.core.models import ChannelSpec, Reading, Zone
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository
from smartgarden.storage.rollup import Tier, run_rollup

START = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def _channel(repo: Repository) -> int:
    repo.upsert_node("pi-local", kind="local", stale_after_seconds=60.0)
    repo.upsert_zone(Zone(slug="windowsill", name="Windowsill"))
    repo.upsert_sensor(
        "soil-monstera", node="pi-local", driver="seesaw_soil", interval_seconds=10.0
    )
    return repo.reconcile_channels(
        "soil-monstera", [ChannelSpec(key="moisture", unit="counts")]
    )["moisture"]


class TestMinuteRollup(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        self.channel_id = _channel(self.repo)

    def test_aggregates_one_minute_bucket(self) -> None:
        values = [400.0, 420.0, 380.0, 410.0]
        for i, value in enumerate(values):
            self.repo.insert_reading(
                Reading(
                    channel_id=self.channel_id,
                    at=START + timedelta(seconds=10 * i),
                    value=value,
                )
            )

        written = run_rollup(self.conn, Tier.MINUTE, START, START + timedelta(minutes=1))
        self.assertEqual(written, 1)

        row = self.conn.execute(
            "SELECT min_value, max_value, mean_value, sample_count FROM reading_rollup "
            "WHERE channel_id = ? AND tier = 'minute'",
            (self.channel_id,),
        ).fetchone()
        self.assertEqual(row["min_value"], 380.0)
        self.assertEqual(row["max_value"], 420.0)
        self.assertAlmostEqual(row["mean_value"], sum(values) / len(values))
        self.assertEqual(row["sample_count"], 4)

    def test_rerunning_over_the_same_window_is_a_no_op(self) -> None:
        for i in range(3):
            self.repo.insert_reading(
                Reading(
                    channel_id=self.channel_id,
                    at=START + timedelta(seconds=10 * i),
                    value=float(i),
                )
            )
        until = START + timedelta(minutes=1)

        select_all = (
            "SELECT min_value, max_value, mean_value, sample_count "
            "FROM reading_rollup ORDER BY bucket_start"
        )
        run_rollup(self.conn, Tier.MINUTE, START, until)
        first = self.conn.execute(select_all).fetchall()

        run_rollup(self.conn, Tier.MINUTE, START, until)
        second = self.conn.execute(select_all).fetchall()

        self.assertEqual([tuple(r) for r in first], [tuple(r) for r in second])
        self.assertEqual(len(second), 1)  # no duplicate row from the re-run

    def test_readings_split_across_two_minute_buckets(self) -> None:
        self.repo.insert_reading(
            Reading(channel_id=self.channel_id, at=START, value=100.0)
        )
        self.repo.insert_reading(
            Reading(
                channel_id=self.channel_id, at=START + timedelta(minutes=1), value=200.0
            )
        )

        run_rollup(self.conn, Tier.MINUTE, START, START + timedelta(minutes=2))

        rows = self.conn.execute(
            "SELECT bucket_start, mean_value FROM reading_rollup ORDER BY bucket_start"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["mean_value"] for r in rows], [100.0, 200.0])


class TestQuarterHourRollup(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        self.channel_id = _channel(self.repo)

    def test_weighted_by_source_count(self) -> None:
        # Two minute buckets feeding one quarter-hour bucket, with different
        # sample counts -- an unweighted average of the means would be wrong.
        for i in range(3):
            self.repo.insert_reading(
                Reading(
                    channel_id=self.channel_id,
                    at=START + timedelta(seconds=10 * i),
                    value=300.0,
                )
            )
        for i in range(1):
            self.repo.insert_reading(
                Reading(
                    channel_id=self.channel_id,
                    at=START + timedelta(minutes=1, seconds=10 * i),
                    value=900.0,
                )
            )
        until = START + timedelta(minutes=15)
        run_rollup(self.conn, Tier.MINUTE, START, until)
        run_rollup(self.conn, Tier.QUARTER_HOUR, START, until)

        row = self.conn.execute(
            "SELECT min_value, max_value, mean_value, sample_count "
            "FROM reading_rollup WHERE tier = 'quarter_hour'"
        ).fetchone()
        self.assertEqual(row["min_value"], 300.0)
        self.assertEqual(row["max_value"], 900.0)
        self.assertEqual(row["sample_count"], 4)
        # weighted: (300*3 + 900*1) / 4 = 450, not the unweighted (300+900)/2 = 600
        self.assertAlmostEqual(row["mean_value"], 450.0)


if __name__ == "__main__":
    unittest.main()

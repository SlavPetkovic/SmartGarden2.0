"""Export: joined CSV covering readings, decisions, actuations and outcomes,
suitable for direct use in a notebook (STOR-5)."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smartgarden.core.models import (
    ActionKind,
    Actuation,
    ChannelRole,
    ChannelSpec,
    Decision,
    DecisionKind,
    DeviceSpec,
    DeviceState,
    Plant,
    Reading,
    Zone,
)
from smartgarden.storage.db import connect
from smartgarden.storage.export import export_range
from smartgarden.storage.repository import Repository

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class TestExportRange(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        self.repo.upsert_node("pi-local", kind="local", stale_after_seconds=60.0)
        self.repo.upsert_zone(Zone(slug="windowsill", name="Windowsill"))
        self.repo.upsert_plant(Plant(slug="monstera", name="Monstera", zone="windowsill"))
        self.repo.upsert_device(
            DeviceSpec(slug="pump-1", kind=ActionKind.IRRIGATE, zone="windowsill", pin=23)
        )
        self.repo.upsert_sensor(
            "soil-monstera", node="pi-local", driver="seesaw_soil", interval_seconds=60.0
        )
        self.channel_id = self.repo.reconcile_channels(
            "soil-monstera",
            [ChannelSpec(key="moisture", unit="counts", role=ChannelRole.SOIL_MOISTURE)],
            zone="windowsill",
            plant="monstera",
        )["moisture"]
        self.repo.insert_reading(Reading(channel_id=self.channel_id, at=NOW, value=650.0))
        self.repo.insert_decision(
            Decision(
                at=NOW,
                zone="windowsill",
                kind=DecisionKind.NO_ACTION,
                reason="soil is wet enough",
            )
        )
        self.repo.insert_actuation(
            Actuation(
                at=NOW,
                zone="windowsill",
                device="pump-1",
                action=ActionKind.IRRIGATE,
                state=DeviceState.ON,
                pre_value=400.0,
                post_value=700.0,
            )
        )

    def test_writes_three_joined_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = export_range(
                self.conn, Path(tmp), NOW - timedelta(hours=1), NOW + timedelta(hours=1)
            )

            self.assertTrue(result.readings.is_file())
            self.assertTrue(result.decisions.is_file())
            self.assertTrue(result.actuations.is_file())

            with result.readings.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["channel"], "moisture")
            self.assertEqual(rows[0]["role"], "soil_moisture")
            self.assertEqual(rows[0]["zone"], "windowsill")
            self.assertEqual(rows[0]["plant"], "monstera")
            self.assertEqual(rows[0]["value"], "650.0")

            with result.decisions.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["kind"], "no_action")
            self.assertEqual(rows[0]["zone"], "windowsill")

            with result.actuations.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["device"], "pump-1")
            # The outcome column is the point of STOR-5's "outcomes": the
            # response derived from pre/post value, not a fourth raw table.
            self.assertEqual(rows[0]["outcome"], "300.0")

    def test_excludes_rows_outside_the_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = export_range(
                self.conn, Path(tmp), NOW + timedelta(days=1), NOW + timedelta(days=2)
            )
            with result.readings.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()

"""The repository: topology, channel reconciliation, readings, decisions,
commands and actuations (DATA-2, DATA-6, ARCH-3, CTRL-8, CTRL-9, STOR-6)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from smartgarden.core.errors import StorageError
from smartgarden.core.models import (
    ActionKind,
    Actuation,
    ChannelRole,
    ChannelSpec,
    Command,
    CommandKind,
    Decision,
    DecisionKind,
    DeviceSpec,
    DeviceState,
    Plant,
    PlantProfile,
    Quality,
    Reading,
    Zone,
)
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _seed(repo: Repository) -> tuple[int, int]:
    """A zone, a plant in it, a device, and a sensor. Returns (sensor_id, device_id)."""
    repo.upsert_node("pi-local", kind="local", stale_after_seconds=60.0)
    repo.upsert_zone(Zone(slug="windowsill", name="Windowsill"))
    repo.upsert_plant(
        Plant(
            slug="monstera",
            name="Monstera",
            zone="windowsill",
            profile=PlantProfile(moisture_low=400.0, moisture_high=900.0),
        )
    )
    device_id = repo.upsert_device(
        DeviceSpec(slug="pump-1", kind=ActionKind.IRRIGATE, zone="windowsill", pin=23)
    )
    sensor_id = repo.upsert_sensor(
        "soil-monstera", node="pi-local", driver="seesaw_soil", interval_seconds=60.0
    )
    return sensor_id, device_id


class TestChannelReconciliation(unittest.TestCase):
    """DATA-2: channel rows are reconciled from a driver's declaration."""

    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        _seed(self.repo)

    def test_declares_and_returns_ids(self) -> None:
        specs = [
            ChannelSpec(key="moisture", unit="counts", role=ChannelRole.SOIL_MOISTURE),
            ChannelSpec(key="temperature", unit="C", role=ChannelRole.SOIL_TEMP),
        ]
        ids = self.repo.reconcile_channels(
            "soil-monstera", specs, zone="windowsill", plant="monstera"
        )
        self.assertEqual(set(ids), {"moisture", "temperature"})
        self.assertIsInstance(ids["moisture"], int)

    def test_reconciling_twice_reuses_the_same_row(self) -> None:
        specs = [
            ChannelSpec(key="moisture", unit="counts", role=ChannelRole.SOIL_MOISTURE)
        ]
        first = self.repo.reconcile_channels("soil-monstera", specs)
        second = self.repo.reconcile_channels("soil-monstera", specs)
        self.assertEqual(first, second)

    def test_reconciling_updates_a_changed_declaration_in_place(self) -> None:
        first = self.repo.reconcile_channels(
            "soil-monstera",
            [ChannelSpec(key="moisture", unit="counts", plausible_max=2000.0)],
        )
        second = self.repo.reconcile_channels(
            "soil-monstera",
            [ChannelSpec(key="moisture", unit="counts", plausible_max=2100.0)],
        )
        self.assertEqual(first, second)  # same row, not a duplicate
        row = self.conn.execute(
            "SELECT plausible_max FROM channel WHERE id = ?", (first["moisture"],)
        ).fetchone()
        self.assertEqual(row["plausible_max"], 2100.0)

    def test_unknown_sensor_is_an_error(self) -> None:
        with self.assertRaises(StorageError):
            self.repo.reconcile_channels("does-not-exist", [])


class TestReadings(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        _seed(self.repo)
        self.channel_id = self.repo.reconcile_channels(
            "soil-monstera",
            [
                ChannelSpec(
                    key="moisture",
                    unit="counts",
                    plausible_min=200.0,
                    plausible_max=2000.0,
                )
            ],
        )["moisture"]

    def test_round_trips_value_and_quality(self) -> None:
        self.repo.insert_reading(
            Reading(
                channel_id=self.channel_id,
                at=NOW,
                value=650.0,
                quality=Quality.OUT_OF_RANGE,
            )
        )
        rows = self.repo.readings_between(
            self.channel_id, NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, 650.0)
        self.assertIs(rows[0].quality, Quality.OUT_OF_RANGE)
        self.assertEqual(rows[0].at, NOW)
        self.assertIsNotNone(rows[0].at.tzinfo)

    def test_bulk_insert(self) -> None:
        readings = [
            Reading(
                channel_id=self.channel_id, at=NOW + timedelta(seconds=i), value=float(i)
            )
            for i in range(5)
        ]
        count = self.repo.insert_readings(readings)
        self.assertEqual(count, 5)
        rows = self.repo.readings_between(
            self.channel_id, NOW, NOW + timedelta(minutes=1)
        )
        self.assertEqual(len(rows), 5)

    def test_range_excludes_readings_outside_the_window(self) -> None:
        self.repo.insert_reading(
            Reading(channel_id=self.channel_id, at=NOW - timedelta(days=1), value=1.0)
        )
        self.repo.insert_reading(Reading(channel_id=self.channel_id, at=NOW, value=2.0))
        rows = self.repo.readings_between(
            self.channel_id, NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)
        )
        self.assertEqual([r.value for r in rows], [2.0])


class TestDecisionsCommandsActuations(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        _seed(self.repo)

    def test_insert_decision(self) -> None:
        decision_id = self.repo.insert_decision(
            Decision(
                at=NOW,
                zone="windowsill",
                kind=DecisionKind.BLOCKED,
                reason="daily budget exhausted",
                inputs={"soil_moisture": 380.0},
            )
        )
        self.assertIsInstance(decision_id, int)
        row = self.conn.execute(
            "SELECT reason FROM decision WHERE id = ?", (decision_id,)
        ).fetchone()
        self.assertEqual(row["reason"], "daily budget exhausted")

    def test_command_lifecycle(self) -> None:
        """ARCH-3: manual actions are queued rows, drained and marked consumed."""
        command_id = self.repo.insert_command(
            Command(
                id=0,
                at=NOW,
                kind=CommandKind.WATER_NOW,
                zone="windowsill",
                issued_by="ui",
            )
        )
        pending = self.repo.pending_commands()
        self.assertEqual([c.id for c in pending], [command_id])
        self.assertTrue(pending[0].pending)

        self.repo.consume_command(command_id, NOW + timedelta(seconds=5))
        self.assertEqual(self.repo.pending_commands(), [])

    def test_insert_actuation_with_outcome(self) -> None:
        actuation_id = self.repo.insert_actuation(
            Actuation(
                at=NOW,
                zone="windowsill",
                device="pump-1",
                action=ActionKind.IRRIGATE,
                state=DeviceState.ON,
                commanded_seconds=6.0,
                actual_seconds=6.0,
                pre_value=420.0,
                post_value=780.0,
                post_at=NOW + timedelta(minutes=10),
            )
        )
        row = self.conn.execute(
            "SELECT pre_value, post_value FROM actuation WHERE id = ?", (actuation_id,)
        ).fetchone()
        self.assertEqual(row["post_value"] - row["pre_value"], 360.0)


if __name__ == "__main__":
    unittest.main()

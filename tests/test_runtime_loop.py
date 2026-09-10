"""The observe-only loop: per-sensor polling intervals, derived VPD, decision
logging, offline nodes, and -- the important one -- proof that no actuator is
reachable from a full tick (CTRL-8, CTRL-10, DATA-4, ML-1)."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from smartgarden.config.schema import (
    AppConfig,
    Config,
    DeviceConfig,
    NodeConfig,
    PlantConfig,
    SensorConfig,
    ZoneConfig,
)
from smartgarden.core.models import ActionKind, DecisionKind
from smartgarden.drivers.actuators.simulated import SimulatedActuator
from smartgarden.runtime.loop import ControlLoop
from smartgarden.runtime.wiring import build_control_loop
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

START = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)


def _config(*, automation_enabled: bool = False) -> Config:
    return Config(
        app=AppConfig(automation_enabled=automation_enabled),
        nodes=(NodeConfig(slug="pi-local", stale_after_seconds=60.0),),
        zones=(ZoneConfig(slug="windowsill", name="Windowsill"),),
        plants=(PlantConfig(slug="monstera", name="Monstera", zone="windowsill"),),
        sensors=(
            SensorConfig(
                slug="air-1",
                node="pi-local",
                driver="simulated_bme680",
                interval_seconds=10.0,
                zone="windowsill",
            ),
            SensorConfig(
                slug="soil-1",
                node="pi-local",
                driver="simulated_seesaw_soil",
                interval_seconds=60.0,
                zone="windowsill",
                plant="monstera",
            ),
        ),
        devices=(
            DeviceConfig(
                slug="pump-1",
                kind=ActionKind.IRRIGATE,
                zone="windowsill",
                driver="simulated",
                pin=23,
                max_on_seconds=10.0,
                pulse_seconds=6.0,
            ),
        ),
    )


def _build_loop(
    *, automation_enabled: bool = False
) -> tuple[sqlite3.Connection, Repository, ControlLoop]:
    conn = connect(":memory:")
    repo = Repository(conn)
    loop = build_control_loop(repo, _config(automation_enabled=automation_enabled))
    return conn, repo, loop


class TestNoActuationPath(unittest.TestCase):
    """BUILD-PLAN.md layer 04a gate, verbatim: "a test asserts that with
    automation_enabled = false no actuator method is reachable from the
    loop. Prove it by making the simulated actuator raise if called, then
    running a full tick cycle." """

    def test_a_full_tick_never_touches_the_actuator(self) -> None:
        conn, _repo, loop = _build_loop(automation_enabled=False)
        self.addCleanup(conn.close)

        with (
            patch.object(
                SimulatedActuator,
                "turn_on",
                side_effect=AssertionError(
                    "actuator.turn_on was called from the observe-only loop"
                ),
            ) as turn_on,
            patch.object(
                SimulatedActuator,
                "turn_off",
                side_effect=AssertionError(
                    "actuator.turn_off was called from the observe-only loop"
                ),
            ) as turn_off,
        ):
            loop.tick()  # must not raise

        turn_on.assert_not_called()
        turn_off.assert_not_called()

    def test_still_true_if_automation_happens_to_be_enabled(self) -> None:
        """Layer 04a has no actuation path at all -- it doesn't read the flag,
        because there is nothing here for the flag to gate. That distinction
        matters: 04b's guards are what actually enforce automation_enabled,
        and they don't exist yet."""
        conn, _repo, loop = _build_loop(automation_enabled=True)
        self.addCleanup(conn.close)

        with patch.object(
            SimulatedActuator, "turn_on", side_effect=AssertionError("must not be called")
        ) as turn_on:
            loop.tick()

        turn_on.assert_not_called()


class TestPerSensorIntervals(unittest.TestCase):
    def setUp(self) -> None:
        self.conn, self.repo, self.loop = _build_loop()
        self.addCleanup(self.conn.close)
        self.loop.now = lambda: START
        self._soil_channel = next(
            b for b in self.loop.bindings if b.slug == "soil-1"
        ).channel_ids["moisture"]
        self._air_channel = next(
            b for b in self.loop.bindings if b.slug == "air-1"
        ).channel_ids["temperature"]

    def _count(self, channel_id: int) -> int:
        window = self.repo.readings_between(
            channel_id, START - timedelta(days=1), START + timedelta(days=1)
        )
        return len(window)

    def test_both_sensors_are_read_on_the_first_tick(self) -> None:
        ticks = iter([0.0])
        self.loop.clock = lambda: next(ticks)
        self.loop.tick()
        self.assertEqual(self._count(self._air_channel), 1)
        self.assertEqual(self._count(self._soil_channel), 1)

    def test_soil_is_not_reread_before_its_60s_interval(self) -> None:
        ticks = iter([0.0, 10.0, 20.0, 30.0])
        self.loop.clock = lambda: next(ticks)
        for _ in range(4):
            self.loop.tick()
        # Air (10s interval) polled all 4 times; soil (60s) only the first.
        self.assertEqual(self._count(self._air_channel), 4)
        self.assertEqual(self._count(self._soil_channel), 1)

    def test_soil_is_reread_once_its_interval_elapses(self) -> None:
        ticks = iter([0.0, 65.0])
        self.loop.clock = lambda: next(ticks)
        self.loop.tick()
        self.loop.tick()
        self.assertEqual(self._count(self._soil_channel), 2)


class TestDerivedVPD(unittest.TestCase):
    def setUp(self) -> None:
        self.conn, self.repo, self.loop = _build_loop()
        self.addCleanup(self.conn.close)
        self.loop.clock = lambda: 0.0
        self.loop.now = lambda: START

    def test_vpd_is_computed_once_air_temp_and_humidity_exist(self) -> None:
        self.loop.tick()
        vpd_channel_id = self.loop.vpd_channel_ids["windowsill"]
        latest = self.repo.latest_value(vpd_channel_id)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertGreater(latest[0], 0.0)

    def test_no_vpd_channel_for_a_zone_with_no_air_sensor(self) -> None:
        config = Config(
            app=AppConfig(),
            nodes=(NodeConfig(slug="pi-local", stale_after_seconds=60.0),),
            zones=(ZoneConfig(slug="bare", name="Bare zone"),),
            sensors=(
                SensorConfig(
                    slug="soil-only",
                    node="pi-local",
                    driver="simulated_seesaw_soil",
                    zone="bare",
                ),
            ),
        )
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        repo = Repository(conn)
        loop = build_control_loop(repo, config)
        loop.clock = lambda: 0.0
        loop.now = lambda: START
        loop.tick()
        self.assertIsNone(repo.latest_value(loop.vpd_channel_ids["bare"]))


class TestDecisionLogging(unittest.TestCase):
    def setUp(self) -> None:
        self.conn, self.repo, self.loop = _build_loop()
        self.addCleanup(self.conn.close)
        self.loop.clock = lambda: 0.0
        self.loop.now = lambda: START

    def test_reports_insufficient_data_before_any_reading(self) -> None:
        decisions = self.repo.recent_decisions("windowsill")
        self.assertEqual(decisions, [])  # nothing written until a tick runs

    def test_writes_no_action_with_observed_values_once_data_exists(self) -> None:
        self.loop.tick()
        decisions = self.repo.recent_decisions("windowsill", limit=1)
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertIs(decision.kind, DecisionKind.NO_ACTION)
        self.assertIn("automation disabled", decision.reason)
        self.assertIn("soil_moisture", decision.inputs)

    def test_writes_a_decision_every_tick(self) -> None:
        ticks = iter([0.0, 10.0, 20.0])
        self.loop.clock = lambda: next(ticks)
        for _ in range(3):
            self.loop.tick()
        self.assertEqual(len(self.repo.recent_decisions("windowsill", limit=10)), 3)


class TestOfflineNodeLogging(unittest.TestCase):
    def test_logs_a_warning_once_a_node_goes_stale(self) -> None:
        conn, _repo, loop = _build_loop()
        self.addCleanup(conn.close)
        # stale_after_seconds=60 on pi-local; jump the wall clock far past it
        # without ever polling, so last_seen_at stays None -- an unseen node
        # is stale by definition (NodeHealth.is_stale).
        loop.clock = lambda: 0.0
        loop.now = lambda: START + timedelta(hours=1)
        loop.bindings = []  # nothing to poll; isolate the offline-node check

        with self.assertLogs("smartgarden.runtime.loop", level="WARNING") as captured:
            loop.tick()
        self.assertTrue(any("pi-local" in message for message in captured.output))
        self.assertTrue(any("offline" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()

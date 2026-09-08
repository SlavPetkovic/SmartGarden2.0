"""Tests for the core domain types.

Mostly invariant tests. The value of a frozen dataclass that validates in
__post_init__ is that an impossible object cannot be constructed at all, so
these are largely about which constructions are refused.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

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
    NodeHealth,
    Observation,
    PlantProfile,
    Quality,
    Reading,
    Zone,
)

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

SOIL = ChannelSpec(
    key="moisture",
    unit="counts",
    role=ChannelRole.SOIL_MOISTURE,
    precision=0,
    plausible_min=180.0,
    plausible_max=2100.0,
)


class TestChannelSpec(unittest.TestCase):
    def test_accepts_plausible_value(self) -> None:
        self.assertIs(SOIL.classify(650.0), Quality.OK)

    def test_flags_implausible_value(self) -> None:
        for value in (0.0, 179.0, 2500.0):
            with self.subTest(value=value):
                self.assertIs(SOIL.classify(value), Quality.OUT_OF_RANGE)

    def test_unbounded_channel_accepts_anything(self) -> None:
        self.assertIs(ChannelSpec(key="gas", unit="ohms").classify(-5.0), Quality.OK)

    def test_rounds_to_declared_precision(self) -> None:
        self.assertEqual(SOIL.round(650.678), 651.0)


class TestReading(unittest.TestCase):
    def test_requires_timezone_aware_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            Reading(channel_id=1, at=datetime(2026, 9, 5, 12, 0), value=1.0)

    def test_defaults_to_ok_quality(self) -> None:
        self.assertIs(Reading(channel_id=1, at=NOW, value=1.0).quality, Quality.OK)


class TestPlantProfile(unittest.TestCase):
    def test_rejects_inverted_moisture_band(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be below"):
            PlantProfile(moisture_low=800.0, moisture_high=400.0)

    def test_rejects_equal_thresholds(self) -> None:
        """A zero-width band is a single threshold, which oscillates."""
        with self.assertRaisesRegex(ValueError, "must be below"):
            PlantProfile(moisture_low=500.0, moisture_high=500.0)

    def test_allows_partial_specification(self) -> None:
        self.assertIsNone(PlantProfile(moisture_low=400.0).moisture_high)

    def test_rejects_impossible_photoperiod_hour(self) -> None:
        for hour in (-1, 24, 99):
            with self.subTest(hour=hour), self.assertRaisesRegex(ValueError, "0-23"):
                PlantProfile(photoperiod_start_hour=hour)


class TestZone(unittest.TestCase):
    def test_defaults_are_conservative(self) -> None:
        zone = Zone(slug="z", name="Z")
        self.assertEqual(zone.daily_budget_seconds, 120.0)
        self.assertEqual(zone.max_pulses_per_hour, 6)

    def test_rejects_impossible_window_hour(self) -> None:
        for hour in (-1, 24):
            with self.subTest(hour=hour), self.assertRaisesRegex(ValueError, "0-23"):
                Zone(slug="z", name="Z", watering_start_hour=hour)

    def test_rejects_negative_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative"):
            Zone(slug="z", name="Z", daily_budget_seconds=-1.0)


class TestDeviceSpec(unittest.TestCase):
    def test_rejects_nonpositive_max_on(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            DeviceSpec(
                slug="p", kind=ActionKind.IRRIGATE, zone="z", pin=23, max_on_seconds=0
            )

    def test_rejects_pin_outside_bcm_range(self) -> None:
        for pin in (-1, 28, 40):
            with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, "BCM pin"):
                DeviceSpec(slug="p", kind=ActionKind.IRRIGATE, zone="z", pin=pin)


class TestObservation(unittest.TestCase):
    def test_returns_present_value(self) -> None:
        obs = Observation(zone="z", at=NOW, values={ChannelRole.SOIL_MOISTURE: 500.0})
        self.assertEqual(obs.get(ChannelRole.SOIL_MOISTURE), 500.0)

    def test_missing_role_is_none(self) -> None:
        self.assertIsNone(Observation(zone="z", at=NOW).get(ChannelRole.SOIL_MOISTURE))

    def test_stale_value_is_hidden(self) -> None:
        """A stale reading must be invisible to rules, not merely flagged.

        Acting on an hour-old moisture value is worse than not acting.
        """
        obs = Observation(
            zone="z",
            at=NOW,
            values={ChannelRole.SOIL_MOISTURE: 500.0},
            stale_roles=frozenset({ChannelRole.SOIL_MOISTURE}),
        )
        self.assertIsNone(obs.get(ChannelRole.SOIL_MOISTURE))

    def test_has_requires_every_role(self) -> None:
        obs = Observation(
            zone="z",
            at=NOW,
            values={ChannelRole.AIR_TEMP: 21.0, ChannelRole.HUMIDITY: 55.0},
        )
        self.assertTrue(obs.has(ChannelRole.AIR_TEMP, ChannelRole.HUMIDITY))
        self.assertFalse(obs.has(ChannelRole.AIR_TEMP, ChannelRole.SOIL_MOISTURE))


class TestDecision(unittest.TestCase):
    def test_act_requires_an_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "must name an action"):
            Decision(at=NOW, zone="z", kind=DecisionKind.ACT)

    def test_rejects_nonpositive_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            Decision(
                at=NOW,
                zone="z",
                kind=DecisionKind.ACT,
                action=ActionKind.IRRIGATE,
                duration_seconds=0.0,
            )

    def test_blocked_is_distinct_from_no_action(self) -> None:
        """These look identical in a boolean and mean opposite things."""
        self.assertIsNot(DecisionKind.BLOCKED, DecisionKind.NO_ACTION)


class TestActuation(unittest.TestCase):
    def test_response_is_the_measured_change(self) -> None:
        act = Actuation(
            at=NOW,
            zone="z",
            device="pump",
            action=ActionKind.IRRIGATE,
            state=DeviceState.ON,
            pre_value=420.0,
            post_value=690.0,
        )
        self.assertAlmostEqual(act.response or 0.0, 270.0, places=9)

    def test_response_unknown_before_settling(self) -> None:
        act = Actuation(
            at=NOW,
            zone="z",
            device="pump",
            action=ActionKind.IRRIGATE,
            state=DeviceState.ON,
            pre_value=420.0,
        )
        self.assertIsNone(act.response)

    def test_commanded_and_actual_are_separate(self) -> None:
        """Their divergence is the signal that a watchdog intervened."""
        act = Actuation(
            at=NOW,
            zone="z",
            device="pump",
            action=ActionKind.IRRIGATE,
            state=DeviceState.OFF,
            commanded_seconds=8.0,
            actual_seconds=3.2,
            forced_off=True,
        )
        self.assertNotEqual(act.commanded_seconds, act.actual_seconds)
        self.assertTrue(act.forced_off)


class TestCommand(unittest.TestCase):
    def test_pending_until_consumed(self) -> None:
        self.assertTrue(Command(id=1, at=NOW, kind=CommandKind.WATER_NOW, zone="z").pending)

    def test_not_pending_once_consumed(self) -> None:
        cmd = Command(id=1, at=NOW, kind=CommandKind.WATER_NOW, zone="z", consumed_at=NOW)
        self.assertFalse(cmd.pending)


class TestNodeHealth(unittest.TestCase):
    def test_never_seen_is_stale(self) -> None:
        health = NodeHealth(node="pi-local", last_seen_at=None, stale_after_seconds=60.0)
        self.assertTrue(health.is_stale(NOW))

    def test_recent_is_fresh(self) -> None:
        health = NodeHealth(
            node="pi-local",
            last_seen_at=NOW - timedelta(seconds=30),
            stale_after_seconds=60.0,
        )
        self.assertFalse(health.is_stale(NOW))

    def test_silence_beyond_threshold_is_stale(self) -> None:
        """A quiet node must read as offline, not as unchanged."""
        health = NodeHealth(
            node="bed-3",
            last_seen_at=NOW - timedelta(seconds=200),
            stale_after_seconds=180.0,
        )
        self.assertTrue(health.is_stale(NOW))


if __name__ == "__main__":
    unittest.main()

"""SimulatedActuator: max_on_seconds is enforced inside the driver, whatever
the caller asks for (SAFE-2)."""

from __future__ import annotations

import unittest

from smartgarden.core.errors import SafetyError
from smartgarden.core.models import ActionKind, DeviceSpec, DeviceState
from smartgarden.drivers.actuators.simulated import SimulatedActuator


def _pump(max_on_seconds: float = 10.0) -> DeviceSpec:
    # Mirrors config/devices.toml's real pump-windowsill: 10s ceiling.
    return DeviceSpec(
        slug="pump-windowsill",
        kind=ActionKind.IRRIGATE,
        zone="windowsill",
        pin=23,
        max_on_seconds=max_on_seconds,
    )


class TestSimulatedActuator(unittest.TestCase):
    def test_a_request_within_the_limit_is_granted_in_full(self) -> None:
        actuator = SimulatedActuator(_pump(max_on_seconds=10.0), clock=lambda: 0.0)
        self.assertEqual(actuator.turn_on(6.0), 6.0)

    def test_a_60s_request_against_a_10s_device_is_clamped_to_10(self) -> None:
        # The exact scenario named in BUILD-PLAN.md's layer 03 gate.
        actuator = SimulatedActuator(_pump(max_on_seconds=10.0), clock=lambda: 0.0)
        self.assertEqual(actuator.turn_on(60.0), 10.0)

    def test_turning_on_changes_state(self) -> None:
        actuator = SimulatedActuator(_pump(), clock=lambda: 100.0)
        self.assertIs(actuator.state, DeviceState.OFF)
        actuator.turn_on(5.0)
        self.assertIs(actuator.state, DeviceState.ON)
        self.assertEqual(actuator.on_since, 100.0)

    def test_turning_off_clears_state(self) -> None:
        actuator = SimulatedActuator(_pump(), clock=lambda: 0.0)
        actuator.turn_on(5.0)
        actuator.turn_off()
        self.assertIs(actuator.state, DeviceState.OFF)
        self.assertIsNone(actuator.on_since)

    def test_a_non_positive_request_is_a_safety_error(self) -> None:
        actuator = SimulatedActuator(_pump(), clock=lambda: 0.0)
        with self.assertRaises(SafetyError):
            actuator.turn_on(0.0)
        with self.assertRaises(SafetyError):
            actuator.turn_on(-1.0)


if __name__ == "__main__":
    unittest.main()

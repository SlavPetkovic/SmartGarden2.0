"""VEML7700: gain and integration time are their own channels, recorded
alongside every lux reading (SENS-5)."""

from __future__ import annotations

import unittest

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole
from smartgarden.drivers.sensors.veml7700 import VEML7700Driver


class FakeDevice:
    def __init__(self, lux: float, gain: float, integration_time: float) -> None:
        self.lux = lux
        self.gain = gain
        self.integration_time = integration_time


class RaisingDevice:
    @property
    def lux(self) -> float:
        raise OSError("bus error")

    gain = 0.0
    integration_time = 0.0


class TestVEML7700Driver(unittest.TestCase):
    def test_lux_carries_the_light_role(self) -> None:
        specs = {c.key: c for c in VEML7700Driver.channels()}
        self.assertEqual(specs["lux"].role, ChannelRole.LIGHT)

    def test_gain_and_integration_time_are_their_own_channels(self) -> None:
        # SENS-5: "a lux value whose gain is unknown is worthless" -- so gain
        # and integration time must be readable channels, not thrown away.
        specs = {c.key: c for c in VEML7700Driver.channels()}
        self.assertIn("gain", specs)
        self.assertIn("integration_time", specs)
        self.assertIsNone(specs["gain"].role)
        self.assertIsNone(specs["integration_time"].role)

    def test_read_reports_lux_gain_and_integration_time_together(self) -> None:
        driver = VEML7700Driver(FakeDevice(lux=8123.0, gain=1.0, integration_time=100.0))
        samples = {s.key: s.value for s in driver.read()}
        self.assertEqual(samples, {"lux": 8123.0, "gain": 1.0, "integration_time": 100.0})

    def test_device_error_becomes_sensor_error(self) -> None:
        driver = VEML7700Driver(RaisingDevice())
        with self.assertRaises(SensorError):
            driver.read()


if __name__ == "__main__":
    unittest.main()

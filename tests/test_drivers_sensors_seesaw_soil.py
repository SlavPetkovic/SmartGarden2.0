"""Seesaw soil: capacitance counts in the sensor's real physical range, not a
percentage."""

from __future__ import annotations

import unittest

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole
from smartgarden.drivers.sensors.seesaw_soil import SeesawSoilDriver


class FakeDevice:
    def __init__(self, moisture: int, temperature: float) -> None:
        self._moisture = moisture
        self._temperature = temperature

    def moisture_read(self) -> int:
        return self._moisture

    def get_temp(self) -> float:
        return self._temperature


class RaisingDevice:
    def moisture_read(self) -> int:
        raise OSError("bus error")

    def get_temp(self) -> float:
        return 20.0


class TestSeesawSoilDriver(unittest.TestCase):
    def test_moisture_channel_matches_the_real_sensors_counts_range(self) -> None:
        spec = next(c for c in SeesawSoilDriver.channels() if c.key == "moisture")
        self.assertEqual(spec.role, ChannelRole.SOIL_MOISTURE)
        self.assertEqual(spec.unit, "counts")
        # docs/BUILD-PLAN.md section 4: ~200 open air, ~2000 fully submerged.
        self.assertLessEqual(spec.plausible_min, 200.0)
        self.assertGreaterEqual(spec.plausible_max, 2000.0)

    def test_read_reports_moisture_and_temperature(self) -> None:
        driver = SeesawSoilDriver(FakeDevice(moisture=612, temperature=19.5))
        samples = {s.key: s.value for s in driver.read()}
        self.assertEqual(samples, {"moisture": 612.0, "temperature": 19.5})

    def test_device_error_becomes_sensor_error(self) -> None:
        driver = SeesawSoilDriver(RaisingDevice())
        with self.assertRaises(SensorError):
            driver.read()


if __name__ == "__main__":
    unittest.main()

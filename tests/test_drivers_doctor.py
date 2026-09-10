"""diagnose(): answered / absent / wrong address, per configured sensor
(SENS-8). Pure -- no bus, no Pi required."""

from __future__ import annotations

import unittest

from smartgarden.drivers.doctor import ConfiguredSensor, diagnose


class TestDiagnose(unittest.TestCase):
    def test_sensor_answers_at_its_configured_address(self) -> None:
        sensors = [ConfiguredSensor(slug="air-1", address=0x77)]
        scans = {(None, None): {0x77, 0x10}}
        results = diagnose(sensors, scans)
        self.assertEqual(results[0].status, "answered")

    def test_sensor_is_absent_when_nothing_answers_on_its_bus(self) -> None:
        sensors = [ConfiguredSensor(slug="soil-1", address=0x36)]
        scans = {(None, None): set()}
        results = diagnose(sensors, scans)
        self.assertEqual(results[0].status, "absent")

    def test_wrong_address_when_something_else_answers_there(self) -> None:
        # The classic BME680 case: configured for 0x77, breakout is at 0x76.
        sensors = [ConfiguredSensor(slug="air-1", address=0x77)]
        scans = {(None, None): {0x76}}
        results = diagnose(sensors, scans)
        self.assertEqual(results[0].status, "wrong_address")
        self.assertIn("0x76", results[0].detail)
        self.assertIn("0x77", results[0].detail)

    def test_missing_scan_for_a_bus_location_counts_as_absent(self) -> None:
        sensors = [
            ConfiguredSensor(slug="soil-1", address=0x36, mux_address=0x70, mux_channel=2)
        ]
        results = diagnose(sensors, {})  # no scan was ever run for that mux channel
        self.assertEqual(results[0].status, "absent")

    def test_sensors_on_different_mux_channels_are_diagnosed_independently(self) -> None:
        sensors = [
            ConfiguredSensor(
                slug="soil-a", address=0x36, mux_address=0x70, mux_channel=0
            ),
            ConfiguredSensor(
                slug="soil-b", address=0x36, mux_address=0x70, mux_channel=1
            ),
        ]
        scans = {(0x70, 0): {0x36}, (0x70, 1): set()}
        results = {r.sensor: r.status for r in diagnose(sensors, scans)}
        self.assertEqual(results, {"soil-a": "answered", "soil-b": "absent"})


if __name__ == "__main__":
    unittest.main()

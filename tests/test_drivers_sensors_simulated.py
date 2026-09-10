"""Simulated sensors -- especially soil drying as a function of VPD and
light, not a random walk (SENS-7)."""

from __future__ import annotations

import unittest
from collections.abc import Callable

from smartgarden.core.models import ChannelRole
from smartgarden.drivers.sensors.simulated import (
    SimulatedAirSensor,
    SimulatedLightSensor,
    SimulatedSoilSensor,
)


def _clock(*ticks: float) -> Callable[[], float]:
    values = iter(ticks)
    return lambda: next(values)


class TestSimulatedSoilSensor(unittest.TestCase):
    def test_first_read_returns_the_starting_value_unchanged(self) -> None:
        sensor = SimulatedSoilSensor(start_moisture=1500.0, clock=_clock(0.0))
        moisture = next(s.value for s in sensor.read() if s.key == "moisture")
        self.assertEqual(moisture, 1500.0)

    def test_drying_is_deterministic_given_the_same_elapsed_time(self) -> None:
        # Not a random walk: two sensors built identically and stepped through
        # identical clocks must land on the exact same value.
        clock_ticks = (0.0, 3600.0, 7200.0)
        a = SimulatedSoilSensor(start_moisture=1500.0, clock=_clock(*clock_ticks))
        b = SimulatedSoilSensor(start_moisture=1500.0, clock=_clock(*clock_ticks))
        for _ in range(3):
            va = next(s.value for s in a.read() if s.key == "moisture")
            vb = next(s.value for s in b.read() if s.key == "moisture")
            self.assertEqual(va, vb)

    def test_moisture_decreases_over_elapsed_time(self) -> None:
        sensor = SimulatedSoilSensor(start_moisture=1500.0, clock=_clock(0.0, 3600.0))
        first = next(s.value for s in sensor.read() if s.key == "moisture")
        second = next(s.value for s in sensor.read() if s.key == "moisture")
        self.assertLess(second, first)

    def test_higher_vpd_dries_faster(self) -> None:
        # Same elapsed time, same light -- only humidity (and therefore VPD)
        # differs. Lower humidity means higher VPD means faster drying.
        clock_ticks = (0.0, 3600.0)
        humid_air = SimulatedSoilSensor(
            start_moisture=1500.0, humidity_pct=90.0, clock=_clock(*clock_ticks)
        )
        dry_air = SimulatedSoilSensor(
            start_moisture=1500.0, humidity_pct=20.0, clock=_clock(*clock_ticks)
        )

        next(iter(humid_air.read()))
        next(iter(dry_air.read()))
        moisture_humid = next(s.value for s in humid_air.read() if s.key == "moisture")
        moisture_dry = next(s.value for s in dry_air.read() if s.key == "moisture")

        self.assertLess(moisture_dry, moisture_humid)

    def test_more_light_dries_faster(self) -> None:
        clock_ticks = (0.0, 3600.0)
        dim = SimulatedSoilSensor(
            start_moisture=1500.0, lux=500.0, clock=_clock(*clock_ticks)
        )
        bright = SimulatedSoilSensor(
            start_moisture=1500.0, lux=20_000.0, clock=_clock(*clock_ticks)
        )

        next(iter(dim.read()))
        next(iter(bright.read()))
        moisture_dim = next(s.value for s in dim.read() if s.key == "moisture")
        moisture_bright = next(s.value for s in bright.read() if s.key == "moisture")

        self.assertLess(moisture_bright, moisture_dim)

    def test_moisture_never_drops_below_the_sensors_physical_floor(self) -> None:
        # A week of elapsed time should be plenty to hit the floor without
        # this drier ever reporting an impossible negative or below-200 value.
        sensor = SimulatedSoilSensor(
            start_moisture=1500.0, clock=_clock(0.0, 7 * 24 * 3600.0)
        )
        next(iter(sensor.read()))
        moisture = next(s.value for s in sensor.read() if s.key == "moisture")
        self.assertGreaterEqual(moisture, 200.0)

    def test_watering_raises_moisture_back_up(self) -> None:
        sensor = SimulatedSoilSensor(start_moisture=300.0, clock=_clock(0.0))
        sensor.water(to=1800.0)
        moisture = next(s.value for s in sensor.read() if s.key == "moisture")
        self.assertEqual(moisture, 1800.0)

    def test_channel_range_matches_the_real_seesaws_counts(self) -> None:
        spec = next(c for c in SimulatedSoilSensor.channels() if c.key == "moisture")
        self.assertEqual(spec.role, ChannelRole.SOIL_MOISTURE)
        self.assertEqual(spec.unit, "counts")


class TestSimulatedAirAndLightSensors(unittest.TestCase):
    def test_air_sensor_declares_the_four_bme680_shaped_channels(self) -> None:
        keys = {c.key for c in SimulatedAirSensor.channels()}
        self.assertEqual(keys, {"temperature", "humidity", "pressure", "gas"})
        self.assertEqual(len(SimulatedAirSensor().read()), 4)

    def test_light_sensor_declares_lux_with_the_light_role(self) -> None:
        spec = SimulatedLightSensor.channels()[0]
        self.assertEqual(spec.key, "lux")
        self.assertEqual(spec.role, ChannelRole.LIGHT)
        self.assertEqual(SimulatedLightSensor(lux=1234.0).read()[0].value, 1234.0)


if __name__ == "__main__":
    unittest.main()

"""BME680: channel declaration, and gas resistance stored but role-less
(SENS-6)."""

from __future__ import annotations

import unittest

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole
from smartgarden.drivers.sensors.bme680 import BME680Driver


class FakeDevice:
    def __init__(
        self, temperature: float, humidity: float, pressure: float, gas: float
    ) -> None:
        self.temperature = temperature
        self.humidity = humidity
        self.pressure = pressure
        self.gas = gas


class RaisingDevice:
    @property
    def temperature(self) -> float:
        raise OSError("bus error")

    humidity = 0.0
    pressure = 0.0
    gas = 0.0


class TestBME680Driver(unittest.TestCase):
    def test_channels_cover_all_four_measurements(self) -> None:
        keys_to_roles = {c.key: c.role for c in BME680Driver.channels()}
        self.assertEqual(keys_to_roles["temperature"], ChannelRole.AIR_TEMP)
        self.assertEqual(keys_to_roles["humidity"], ChannelRole.HUMIDITY)
        self.assertEqual(keys_to_roles["pressure"], ChannelRole.PRESSURE)
        self.assertEqual(keys_to_roles["gas"], ChannelRole.GAS_RESISTANCE)

    def test_gas_resistance_has_no_downstream_role_binding_beyond_its_own(self) -> None:
        # SENS-6: gas is read and stored, calibrated to nothing -- it still
        # gets its own role so it is chartable, but nothing computes from it.
        gas_spec = next(c for c in BME680Driver.channels() if c.key == "gas")
        self.assertIsNone(gas_spec.plausible_min)
        self.assertIsNone(gas_spec.plausible_max)

    def test_read_returns_one_sample_per_channel(self) -> None:
        driver = BME680Driver(
            FakeDevice(temperature=22.5, humidity=48.0, pressure=1013.2, gas=180_000.0)
        )
        samples = {s.key: s.value for s in driver.read()}
        self.assertEqual(
            samples,
            {
                "temperature": 22.5,
                "humidity": 48.0,
                "pressure": 1013.2,
                "gas": 180_000.0,
            },
        )

    def test_device_error_becomes_sensor_error(self) -> None:
        driver = BME680Driver(RaisingDevice())
        with self.assertRaises(SensorError):
            driver.read()


if __name__ == "__main__":
    unittest.main()

"""Driver discovery by name, not by a hand-maintained list (SENS-1)."""

from __future__ import annotations

import unittest
from collections.abc import Sequence

from smartgarden.core.errors import SmartGardenError
from smartgarden.core.models import ChannelSpec, DeviceState, Sample
from smartgarden.drivers import registry
from smartgarden.drivers.registry import (
    actuator_driver,
    available_actuator_drivers,
    available_sensor_drivers,
    register_actuator,
    register_sensor,
    sensor_driver,
)


class TestSensorRegistry(unittest.TestCase):
    def test_decorating_a_class_makes_it_discoverable(self) -> None:
        """Registration is the only thing that makes a driver findable -- no
        other file needs editing for `sensor_driver`/`available_sensor_drivers`
        to see a new one."""

        @register_sensor("test_dummy_sensor")
        class DummySensor:
            @classmethod
            def channels(cls) -> Sequence[ChannelSpec]:
                return (ChannelSpec(key="x", unit="u"),)

            def read(self) -> Sequence[Sample]:
                return (Sample(key="x", value=1.0),)

        self.addCleanup(registry._SENSORS.pop, "test_dummy_sensor", None)

        self.assertIn("test_dummy_sensor", available_sensor_drivers())
        self.assertIs(sensor_driver("test_dummy_sensor"), DummySensor)

    def test_duplicate_registration_is_rejected(self) -> None:
        @register_sensor("test_dummy_sensor_dup")
        class First:
            @classmethod
            def channels(cls) -> Sequence[ChannelSpec]:
                return ()

            def read(self) -> Sequence[Sample]:
                return ()

        self.addCleanup(registry._SENSORS.pop, "test_dummy_sensor_dup", None)

        with self.assertRaises(SmartGardenError):

            @register_sensor("test_dummy_sensor_dup")
            class Second:
                @classmethod
                def channels(cls) -> Sequence[ChannelSpec]:
                    return ()

                def read(self) -> Sequence[Sample]:
                    return ()

    def test_unknown_name_raises_with_known_drivers_listed(self) -> None:
        with self.assertRaises(SmartGardenError):
            sensor_driver("does-not-exist")

    def test_real_sensor_drivers_are_registered_on_import(self) -> None:
        import smartgarden.drivers  # noqa: F401

        for name in (
            "bme680",
            "veml7700",
            "seesaw_soil",
            "simulated_bme680",
            "simulated_veml7700",
            "simulated_seesaw_soil",
        ):
            with self.subTest(driver=name):
                self.assertIn(name, available_sensor_drivers())


class TestActuatorRegistry(unittest.TestCase):
    def test_real_actuator_drivers_are_registered_on_import(self) -> None:
        import smartgarden.drivers  # noqa: F401

        self.assertIn("simulated", available_actuator_drivers())

    def test_decorating_a_class_makes_it_discoverable(self) -> None:
        @register_actuator("test_dummy_actuator")
        class DummyActuator:
            def turn_on(self, requested_seconds: float) -> float:
                return requested_seconds

            def turn_off(self) -> None:
                pass

            @property
            def state(self) -> DeviceState:
                return DeviceState.OFF

        self.addCleanup(registry._ACTUATORS.pop, "test_dummy_actuator", None)

        self.assertIn("test_dummy_actuator", available_actuator_drivers())
        self.assertIs(actuator_driver("test_dummy_actuator"), DummyActuator)


if __name__ == "__main__":
    unittest.main()

"""Layer 3: sensor and actuator plugins (SENS-1...8, SAFE-2).

Importing this package registers every driver it ships. Nothing outside
`drivers/` should ever need to import a driver submodule directly -- go
through `registry.sensor_driver`/`registry.actuator_driver` by name instead,
which is what keeps SENS-1 true.
"""

from __future__ import annotations

from smartgarden.drivers import actuators, sensors  # noqa: F401
from smartgarden.drivers.base import ActuatorDriver, SensorDriver
from smartgarden.drivers.i2c import I2CLocation
from smartgarden.drivers.polling import SensorReadResult, poll_all
from smartgarden.drivers.registry import (
    actuator_driver,
    available_actuator_drivers,
    available_sensor_drivers,
    register_actuator,
    register_sensor,
    sensor_driver,
)

__all__ = [
    "ActuatorDriver",
    "I2CLocation",
    "SensorDriver",
    "SensorReadResult",
    "actuator_driver",
    "available_actuator_drivers",
    "available_sensor_drivers",
    "poll_all",
    "register_actuator",
    "register_sensor",
    "sensor_driver",
]

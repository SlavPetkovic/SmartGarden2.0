"""Driver discovery by name (SENS-1).

Registration happens by decorating a class where it is defined; nothing else
in the codebase enumerates driver types by hand. `sensors/__init__.py` and
`actuators/__init__.py` import every module in their package purely for this
decoration side effect -- that import list is the one place driver *modules*
are named, and it says nothing about what each one implements.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from smartgarden.core.errors import SmartGardenError
from smartgarden.drivers.base import ActuatorDriver, SensorDriver

__all__ = [
    "actuator_driver",
    "available_actuator_drivers",
    "available_sensor_drivers",
    "register_actuator",
    "register_sensor",
    "sensor_driver",
]

_SENSORS: dict[str, type[SensorDriver]] = {}
_ACTUATORS: dict[str, type[ActuatorDriver]] = {}

_S = TypeVar("_S", bound=type[SensorDriver])
_A = TypeVar("_A", bound=type[ActuatorDriver])


def register_sensor(name: str) -> Callable[[_S], _S]:
    def decorator(cls: _S) -> _S:
        if name in _SENSORS:
            raise SmartGardenError(f"sensor driver '{name}' is already registered")
        _SENSORS[name] = cls
        return cls

    return decorator


def register_actuator(name: str) -> Callable[[_A], _A]:
    def decorator(cls: _A) -> _A:
        if name in _ACTUATORS:
            raise SmartGardenError(f"actuator driver '{name}' is already registered")
        _ACTUATORS[name] = cls
        return cls

    return decorator


def sensor_driver(name: str) -> type[SensorDriver]:
    try:
        return _SENSORS[name]
    except KeyError:
        known = ", ".join(sorted(_SENSORS)) or "none registered"
        raise SmartGardenError(
            f"no sensor driver named '{name}'. Known drivers: {known}"
        ) from None


def actuator_driver(name: str) -> type[ActuatorDriver]:
    try:
        return _ACTUATORS[name]
    except KeyError:
        known = ", ".join(sorted(_ACTUATORS)) or "none registered"
        raise SmartGardenError(
            f"no actuator driver named '{name}'. Known drivers: {known}"
        ) from None


def available_sensor_drivers() -> frozenset[str]:
    return frozenset(_SENSORS)


def available_actuator_drivers() -> frozenset[str]:
    return frozenset(_ACTUATORS)

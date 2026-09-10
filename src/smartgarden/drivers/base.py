"""Driver protocols (SENS-1).

`channels()` is a classmethod: what a driver measures is static per driver
*type*, not per instance, so channel rows can be reconciled (DATA-2) at
startup from the class alone -- before any hardware has answered, and
regardless of whether it ever does (DATA-4: absent is a valid state, not an
error). `read()` needs a live instance because it needs a live device.

Nothing outside `drivers/` should need to know these are `Protocol`s rather
than a shared base class; either satisfies static type checking the same way.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from smartgarden.core.models import ChannelSpec, DeviceState, Sample

__all__ = ["ActuatorDriver", "SensorDriver"]


@runtime_checkable
class SensorDriver(Protocol):
    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        """The channels this driver type produces, independent of hardware state."""
        ...

    def read(self) -> Sequence[Sample]:
        """One value per declared channel, or raise SensorError/TransientError."""
        ...


@runtime_checkable
class ActuatorDriver(Protocol):
    def turn_on(self, requested_seconds: float) -> float:
        """Turn the output on and return the duration actually granted.

        The driver clamps `requested_seconds` to its own hard limit
        regardless of what is asked for (SAFE-2) -- the caller's job is to
        turn it off again after the returned duration, not before assuming
        it will run for what it asked.
        """
        ...

    def turn_off(self) -> None: ...

    @property
    def state(self) -> DeviceState: ...

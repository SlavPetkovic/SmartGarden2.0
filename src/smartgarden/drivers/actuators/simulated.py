"""Simulated actuator: logs what it would have done and touches no hardware
(config/devices.toml's own description of `driver = "simulated"`).

`max_on_seconds` is enforced here, inside the driver, whatever the caller
asks for (SAFE-2) -- the last line of defence that still lives in the
process, ahead of the watchdog and the systemd stop hook that come in layer
04b.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from smartgarden.core.errors import SafetyError
from smartgarden.core.models import DeviceSpec, DeviceState
from smartgarden.drivers.registry import register_actuator

__all__ = ["SimulatedActuator"]


@register_actuator("simulated")
class SimulatedActuator:
    def __init__(
        self, spec: DeviceSpec, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._state = DeviceState.OFF
        self._on_since: float | None = None

    def turn_on(self, requested_seconds: float) -> float:
        if requested_seconds <= 0:
            raise SafetyError(
                f"requested_seconds must be positive, got {requested_seconds}"
            )
        granted = min(requested_seconds, self._spec.max_on_seconds)
        self._state = DeviceState.ON
        self._on_since = self._clock()
        return granted

    def turn_off(self) -> None:
        self._state = DeviceState.OFF
        self._on_since = None

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def on_since(self) -> float | None:
        return self._on_since

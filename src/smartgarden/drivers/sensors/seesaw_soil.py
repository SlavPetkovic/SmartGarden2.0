"""Adafruit STEMMA Seesaw -- soil moisture (capacitance counts) and temperature.

The Seesaw reports raw capacitance, roughly 200 in open air to 2000 fully
submerged (docs/BUILD-PLAN.md §4) -- there is no percentage, and no plausible
threshold until the soak (stage B) measures this soil and this probe depth.
`plausible_min`/`plausible_max` here are the sensor's physical range, not a
dry/wet threshold; nothing in this codebase invents one of those.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole, ChannelSpec, Sample
from smartgarden.drivers.i2c import I2CLocation, open_bus
from smartgarden.drivers.registry import register_sensor

__all__ = ["SeesawSoilDevice", "SeesawSoilDriver", "create"]

DEFAULT_ADDRESS = 0x36


class SeesawSoilDevice(Protocol):
    """The slice of `adafruit_seesaw.seesaw.Seesaw` this driver uses."""

    def moisture_read(self) -> int: ...
    def get_temp(self) -> float: ...


@register_sensor("seesaw_soil")
class SeesawSoilDriver:
    def __init__(self, device: SeesawSoilDevice) -> None:
        self._device = device

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (
            ChannelSpec(
                key="moisture",
                unit="counts",
                role=ChannelRole.SOIL_MOISTURE,
                precision=0,
                plausible_min=180.0,
                plausible_max=2100.0,
            ),
            ChannelSpec(
                key="temperature",
                unit="C",
                role=ChannelRole.SOIL_TEMP,
                plausible_min=-10.0,
                plausible_max=50.0,
            ),
        )

    def read(self) -> Sequence[Sample]:
        try:
            return (
                Sample(key="moisture", value=float(self._device.moisture_read())),
                Sample(key="temperature", value=float(self._device.get_temp())),
            )
        except OSError as exc:
            raise SensorError(f"Seesaw soil read failed: {exc}") from exc


def create(
    location: I2CLocation | None = None, *, address: int = DEFAULT_ADDRESS
) -> SeesawSoilDriver:
    """Build a driver against real hardware. Pi-only; not covered by the suite."""
    try:
        from adafruit_seesaw.seesaw import Seesaw
    except ImportError as exc:
        raise SensorError(
            "adafruit-circuitpython-seesaw is not installed. "
            "On the Pi: pip install -e '.[pi]'"
        ) from exc
    i2c = open_bus(location)
    device = Seesaw(i2c, addr=address)
    return SeesawSoilDriver(device)

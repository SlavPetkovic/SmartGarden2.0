"""VEML7700 -- ambient light (SENS-5).

Gain and integration time are set explicitly in `create()`, never left at
whatever the sensor powers on with, and both are recorded as their own
channels alongside `lux` on every read -- a lux value whose gain is unknown
is worthless, and DATA-1's narrow-row model means "recorded alongside" is
just two more rows on the same tick rather than metadata bolted onto one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole, ChannelSpec, Sample
from smartgarden.drivers.i2c import I2CLocation, open_bus
from smartgarden.drivers.registry import register_sensor

__all__ = ["VEML7700Device", "VEML7700Driver", "create"]

DEFAULT_ADDRESS = 0x10


class VEML7700Device(Protocol):
    """The slice of `adafruit_veml7700.VEML7700` this driver uses.

    `gain` and `integration_time` are the raw driver-code values the
    underlying library uses (not physical units) -- they are recorded as-is
    so a person reading the export can match them back to that library's
    constants; converting them to a physical gain factor / millisecond
    figure belongs to whoever consumes the export, not to this driver.
    """

    lux: float
    gain: float
    integration_time: float


@register_sensor("veml7700")
class VEML7700Driver:
    def __init__(self, device: VEML7700Device) -> None:
        self._device = device

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (
            ChannelSpec(key="lux", unit="lux", role=ChannelRole.LIGHT, plausible_min=0.0),
            ChannelSpec(key="gain", unit="code", precision=3),
            ChannelSpec(key="integration_time", unit="code", precision=3),
        )

    def read(self) -> Sequence[Sample]:
        try:
            return (
                Sample(key="lux", value=float(self._device.lux)),
                Sample(key="gain", value=float(self._device.gain)),
                Sample(
                    key="integration_time", value=float(self._device.integration_time)
                ),
            )
        except OSError as exc:
            raise SensorError(f"VEML7700 read failed: {exc}") from exc


def create(
    location: I2CLocation | None = None, *, address: int = DEFAULT_ADDRESS
) -> VEML7700Driver:
    """Build a driver against real hardware, with gain/integration time set
    explicitly rather than left at the power-on default. Pi-only; not
    covered by the suite -- confirm the exact constant names against the
    installed `adafruit-circuitpython-veml7700` version on first wiring.
    """
    try:
        import adafruit_veml7700
    except ImportError as exc:
        raise SensorError(
            "adafruit-circuitpython-veml7700 is not installed. "
            "On the Pi: pip install -e '.[pi]'"
        ) from exc
    i2c = open_bus(location)
    device = adafruit_veml7700.VEML7700(i2c, address=address)
    device.gain = device.ALS_GAIN_1
    device.integration_time = device.ALS_100MS
    return VEML7700Driver(device)

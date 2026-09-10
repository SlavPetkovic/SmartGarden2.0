"""BME680 -- air temperature, humidity, pressure, gas resistance (SENS-6).

Gas resistance is read and stored but used by nothing: it needs a burn-in
period and is calibrated to no known reference, so treating it as anything
but a diagnostic value would be inventing a threshold (SENS-6).

`BME680Driver` takes an already-constructed device object rather than an I2C
bus, so it is fully testable with a fake that only needs the four attributes
the real `adafruit_bme680` library exposes -- no hardware, no `[pi]` extra,
required to run `tests/test_drivers_sensors_bme680.py`. `create()` is the
thin, hardware-only half that builds the real device; it is exercised on the
Pi, not in the suite.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelRole, ChannelSpec, Sample
from smartgarden.drivers.i2c import I2CLocation, open_bus
from smartgarden.drivers.registry import register_sensor

__all__ = ["BME680Device", "BME680Driver", "create"]

DEFAULT_ADDRESS = 0x77


class BME680Device(Protocol):
    """The slice of `adafruit_bme680.Adafruit_BME680_I2C` this driver uses."""

    temperature: float
    humidity: float
    pressure: float
    gas: float


@register_sensor("bme680")
class BME680Driver:
    def __init__(self, device: BME680Device) -> None:
        self._device = device

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (
            ChannelSpec(
                key="temperature",
                unit="C",
                role=ChannelRole.AIR_TEMP,
                plausible_min=-10.0,
                plausible_max=50.0,
            ),
            ChannelSpec(
                key="humidity",
                unit="%",
                role=ChannelRole.HUMIDITY,
                plausible_min=0.0,
                plausible_max=100.0,
            ),
            ChannelSpec(
                key="pressure",
                unit="hPa",
                role=ChannelRole.PRESSURE,
                plausible_min=800.0,
                plausible_max=1100.0,
            ),
            ChannelSpec(
                key="gas",
                unit="ohm",
                role=ChannelRole.GAS_RESISTANCE,
                precision=0,
            ),
        )

    def read(self) -> Sequence[Sample]:
        try:
            return (
                Sample(key="temperature", value=float(self._device.temperature)),
                Sample(key="humidity", value=float(self._device.humidity)),
                Sample(key="pressure", value=float(self._device.pressure)),
                Sample(key="gas", value=float(self._device.gas)),
            )
        except OSError as exc:
            raise SensorError(f"BME680 read failed: {exc}") from exc


def create(
    location: I2CLocation | None = None, *, address: int = DEFAULT_ADDRESS
) -> BME680Driver:
    """Build a driver against real hardware. Pi-only; not covered by the suite."""
    try:
        import adafruit_bme680
    except ImportError as exc:
        raise SensorError(
            "adafruit-circuitpython-bme680 is not installed. "
            "On the Pi: pip install -e '.[pi]'"
        ) from exc
    i2c = open_bus(location)
    device = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=address)
    return BME680Driver(device)

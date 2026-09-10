"""I2C wiring: bus location and multiplexer support (SENS-4, PLAT-2).

Every real sensor driver factory and `doctor` go through `open_bus()` rather
than importing `board`/`busio`/`adafruit_tca9548a` themselves, so there is
exactly one place that decides how a mux channel is selected and exactly one
place a missing hardware extra turns into a `SensorError` instead of an
`ImportError` a caller wasn't expecting.

Imports are deliberately inside the functions, not at module level: this
module must be importable on a laptop with no `[pi]` extra installed (PLAT-4,
CLAUDE.md hard rule 7), which is what lets the rest of `drivers/` -- and
anything that imports it, like the driver registry -- load everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smartgarden.core.errors import SensorError

__all__ = ["I2CLocation", "open_bus", "scan"]


@dataclass(frozen=True, slots=True)
class I2CLocation:
    """Where a sensor sits: a bare address, or an address behind a mux channel."""

    address: int
    mux_address: int | None = None
    mux_channel: int | None = None

    def __post_init__(self) -> None:
        if (self.mux_address is None) != (self.mux_channel is None):
            raise ValueError("set both mux_address and mux_channel, or neither")


def open_bus(location: I2CLocation | None = None) -> Any:
    """The shared bus, or a mux channel's view of it, ready to hand to a device.

    `location` may be omitted (or carry no mux fields) for a sensor wired
    directly to the main bus. Raises `SensorError` -- never `ImportError` --
    when the `[pi]` extra is not installed or the mux does not answer.
    """
    try:
        import board
        import busio
    except ImportError as exc:
        raise SensorError(
            "I2C hardware libraries are not installed. On the Pi: pip install -e '.[pi]'"
        ) from exc

    i2c = busio.I2C(board.SCL, board.SDA)
    if location is None or location.mux_address is None:
        return i2c

    try:
        import adafruit_tca9548a
    except ImportError as exc:
        raise SensorError(
            "adafruit-circuitpython-tca9548a is not installed, but a mux "
            "address was configured. On the Pi: pip install -e '.[pi]'"
        ) from exc

    mux = adafruit_tca9548a.TCA9548A(i2c, address=location.mux_address)
    return mux[location.mux_channel]


def scan(location: I2CLocation | None = None) -> set[int]:
    """Every address that answers on this bus (or mux channel) right now.

    This is what `smartgarden doctor` (SENS-8) is built on: it says what is
    physically present, independent of what `config/sensors.toml` claims.
    """
    bus = open_bus(location)
    while not bus.try_lock():
        pass
    try:
        return set(bus.scan())
    finally:
        bus.unlock()

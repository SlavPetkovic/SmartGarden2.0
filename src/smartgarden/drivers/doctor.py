"""`smartgarden doctor`: what's physically present, not what config claims
(SENS-8).

`diagnose` is the part a test exercises without a Pi -- pure, given a scan
result per bus location. `run_doctor` is the thin, untested-except-on-the-Pi
wiring that actually touches the bus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from smartgarden.drivers.i2c import I2CLocation, scan

__all__ = ["ConfiguredSensor", "SensorDiagnosis", "diagnose", "run_doctor"]

Status = Literal["answered", "absent", "wrong_address"]

# (mux_address, mux_channel); (None, None) means the main bus.
BusKey = tuple[int | None, int | None]


@dataclass(frozen=True, slots=True)
class ConfiguredSensor:
    """The minimum a diagnosis needs to know about one configured sensor.

    Deliberately not `config.schema.SensorConfig` -- doctor cares about bus
    wiring, not zones, plants or roles, and drivers stay decoupled from the
    config layer entirely.
    """

    slug: str
    address: int
    mux_address: int | None = None
    mux_channel: int | None = None

    @property
    def bus_key(self) -> BusKey:
        return (self.mux_address, self.mux_channel)


@dataclass(frozen=True, slots=True)
class SensorDiagnosis:
    sensor: str
    address: int
    status: Status
    detail: str = ""


def diagnose(
    sensors: Sequence[ConfiguredSensor], scans: Mapping[BusKey, set[int]]
) -> list[SensorDiagnosis]:
    """Compare configured sensors against what each bus location's scan found.

    `scans` is one scan per distinct `(mux_address, mux_channel)`, since
    several sensors can share a location and a single scan finds all of them.
    """
    results: list[SensorDiagnosis] = []
    for sensor in sensors:
        found = scans.get(sensor.bus_key, set())
        if sensor.address in found:
            results.append(SensorDiagnosis(sensor.slug, sensor.address, "answered"))
        elif not found:
            results.append(SensorDiagnosis(sensor.slug, sensor.address, "absent"))
        else:
            others = ", ".join(f"0x{a:02x}" for a in sorted(found))
            results.append(
                SensorDiagnosis(
                    sensor.slug,
                    sensor.address,
                    "wrong_address",
                    detail=f"expected 0x{sensor.address:02x}, found {others}",
                )
            )
    return results


def run_doctor(sensors: Sequence[ConfiguredSensor]) -> list[SensorDiagnosis]:
    """Scan every distinct bus location once, then diagnose against it.

    The only function in this module that touches real hardware.
    """
    locations: dict[BusKey, I2CLocation] = {}
    for sensor in sensors:
        locations.setdefault(
            sensor.bus_key,
            I2CLocation(sensor.address, sensor.mux_address, sensor.mux_channel),
        )
    scans = {key: scan(location) for key, location in locations.items()}
    return diagnose(sensors, scans)

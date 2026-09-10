"""Simulated sensors: stand in for hardware that isn't wired yet.

Nothing here reads a config file or a role -- these are driver-layer stand-ins
for real chips, config just points a `[[sensor]]` block's `driver` at one of
these names instead of `bme680`/`veml7700`/`seesaw_soil` (CLAUDE.md: "No
actuators yet. Simulated drivers stand in").
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from smartgarden.core.models import ChannelRole, ChannelSpec, Sample
from smartgarden.core.physics import vapour_pressure_deficit
from smartgarden.drivers.registry import register_sensor

__all__ = ["SimulatedAirSensor", "SimulatedLightSensor", "SimulatedSoilSensor"]

# The real Seesaw's physical range (docs/BUILD-PLAN.md section 4): roughly 200
# in open air, roughly 2000 fully submerged. Not a dry/wet threshold -- that
# number does not exist until the soak (stage B) measures this soil.
_MOISTURE_MIN = 200.0
_MOISTURE_MAX = 2000.0


@register_sensor("simulated_bme680")
class SimulatedAirSensor:
    """A steady indoor room. No weather model -- nothing here needs one yet."""

    def __init__(
        self, *, temperature_c: float = 22.0, humidity_pct: float = 48.0
    ) -> None:
        self._temperature_c = temperature_c
        self._humidity_pct = humidity_pct

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (
            ChannelSpec(key="temperature", unit="C", role=ChannelRole.AIR_TEMP),
            ChannelSpec(key="humidity", unit="%", role=ChannelRole.HUMIDITY),
            ChannelSpec(key="pressure", unit="hPa", role=ChannelRole.PRESSURE),
            ChannelSpec(
                key="gas", unit="ohm", role=ChannelRole.GAS_RESISTANCE, precision=0
            ),
        )

    def read(self) -> Sequence[Sample]:
        return (
            Sample(key="temperature", value=self._temperature_c),
            Sample(key="humidity", value=self._humidity_pct),
            Sample(key="pressure", value=1013.0),
            Sample(key="gas", value=150_000.0),
        )


@register_sensor("simulated_veml7700")
class SimulatedLightSensor:
    """A fixed daylight level. No diurnal cycle -- nothing here needs one yet."""

    def __init__(self, *, lux: float = 8000.0) -> None:
        self._lux = lux

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (
            ChannelSpec(key="lux", unit="lux", role=ChannelRole.LIGHT, plausible_min=0.0),
        )

    def read(self) -> Sequence[Sample]:
        return (Sample(key="lux", value=self._lux),)


@register_sensor("simulated_seesaw_soil")
class SimulatedSoilSensor:
    """Soil that dries at a rate driven by VPD and light, not a random walk
    (SENS-7).

    Emits capacitance counts in the real Seesaw's 200-2000 range rather than
    a percentage -- a mock that emitted a unit the real sensor never produces
    would hide the counts-to-plausible-range conversion instead of exercising
    it the same way the real driver has to.
    """

    def __init__(
        self,
        *,
        start_moisture: float = 1400.0,
        temperature_c: float = 24.0,
        humidity_pct: float = 45.0,
        lux: float = 8000.0,
        drying_rate_per_kpa_per_klux: float = 6.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._moisture = start_moisture
        self._temperature_c = temperature_c
        self._humidity_pct = humidity_pct
        self._lux = lux
        self._rate = drying_rate_per_kpa_per_klux
        self._clock = clock
        self._last_read: float | None = None

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
            ChannelSpec(key="temperature", unit="C", role=ChannelRole.SOIL_TEMP),
        )

    def water(self, *, to: float = 1800.0) -> None:
        """A pulse landing: jump moisture back up, clamped to the sensor's range."""
        self._moisture = min(to, _MOISTURE_MAX)

    def read(self) -> Sequence[Sample]:
        now = self._clock()
        if self._last_read is not None:
            elapsed_hours = (now - self._last_read) / 3600.0
            vpd = vapour_pressure_deficit(self._temperature_c, self._humidity_pct)
            drying = self._rate * vpd * (self._lux / 1000.0) * elapsed_hours
            self._moisture = max(_MOISTURE_MIN, self._moisture - drying)
        self._last_read = now
        return (
            Sample(key="moisture", value=self._moisture),
            Sample(key="temperature", value=self._temperature_c),
        )

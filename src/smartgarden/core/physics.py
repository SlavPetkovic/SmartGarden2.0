"""Atmospheric and horticultural physics.

Pure functions over floats. No I/O, no state, no imports from the rest of the
package -- everything here is unit-testable in isolation and safe to call from
anywhere.

Formulae and their provenance are documented inline because the constants are
easy to transcribe wrongly and impossible to eyeball afterwards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

__all__ = [
    "MAGNUS_A",
    "MAGNUS_B",
    "SUNLIGHT_LUX_PER_PPFD",
    "saturation_vapour_pressure",
    "actual_vapour_pressure",
    "vapour_pressure_deficit",
    "dew_point",
    "absolute_humidity",
    "relative_humidity_from_dew_point",
    "lux_to_ppfd",
    "dli_increment",
    "pressure_to_altitude",
    "DliAccumulator",
]


# Alduchov & Eskridge (1996) refinement of the Magnus-Tetens coefficients.
# Accurate to about 0.4% over -40..50 C, which is better than our sensors.
MAGNUS_A = 17.625
MAGNUS_B = 243.04  # degrees Celsius

# Saturation vapour pressure at 0 C, in kilopascals.
_ES_0C_KPA = 0.61094

# Standard atmosphere, for the barometric altitude approximation.
_SEA_LEVEL_KPA = 101.325
_ALTITUDE_COEFF = 44330.0
_ALTITUDE_EXPONENT = 1.0 / 5.255

# Molar mass of water over the specific gas constant for water vapour,
# pre-combined for the absolute-humidity expression.
_AH_COEFF = 2165.0  # (g*K)/(m^3*kPa)

# Lux per micromole per square metre per second, for daylight.
#
# This ratio is spectrum-dependent: lux is weighted by human photopic response,
# PPFD counts photons between 400-700 nm. The daylight figure is the usual
# textbook value. White LED fixtures typically land between 70 and 90, and a
# red/blue "blurple" fixture can exceed 200 -- which is why the conversion
# factor is configurable per fixture rather than hard-coded at the call site.
SUNLIGHT_LUX_PER_PPFD = 54.0


def saturation_vapour_pressure(temperature_c: float) -> float:
    """Saturation vapour pressure of air, in kPa.

    The pressure water vapour would exert if the air were fully saturated at
    this temperature. Rises steeply and non-linearly with temperature, which is
    why warm air dries soil so much faster than cool air at the same relative
    humidity.
    """
    return _ES_0C_KPA * math.exp(
        (MAGNUS_A * temperature_c) / (temperature_c + MAGNUS_B)
    )


def actual_vapour_pressure(temperature_c: float, relative_humidity_pct: float) -> float:
    """Actual vapour pressure of air, in kPa."""
    _check_humidity(relative_humidity_pct)
    return saturation_vapour_pressure(temperature_c) * (relative_humidity_pct / 100.0)


def vapour_pressure_deficit(
    temperature_c: float, relative_humidity_pct: float
) -> float:
    """Vapour pressure deficit, in kPa.

    The difference between how much moisture the air is holding and how much it
    could hold. This is the physical driver of transpiration -- and therefore of
    how fast soil dries -- far more directly than relative humidity, which means
    nothing without its temperature.

    Note this is *air* VPD. True leaf VPD uses leaf surface temperature, which
    is typically a degree or two below air temperature under a grow light. We
    do not measure leaf temperature, so this is an approximation that is
    consistently biased low. It is still by far the best drying predictor
    available from the sensors we have.
    """
    _check_humidity(relative_humidity_pct)
    return saturation_vapour_pressure(temperature_c) * (
        1.0 - relative_humidity_pct / 100.0
    )


def dew_point(temperature_c: float, relative_humidity_pct: float) -> float:
    """Dew point temperature, in degrees Celsius.

    The temperature at which this air would begin to condense. Useful for
    condensation warnings in an enclosure and as a sanity check on the humidity
    sensor: a dew point above air temperature is physically impossible and means
    the sensor is lying.
    """
    _check_humidity(relative_humidity_pct)
    if relative_humidity_pct <= 0.0:
        raise ValueError("dew point is undefined at 0% relative humidity")

    gamma = math.log(relative_humidity_pct / 100.0) + (
        MAGNUS_A * temperature_c
    ) / (temperature_c + MAGNUS_B)
    return (MAGNUS_B * gamma) / (MAGNUS_A - gamma)


def absolute_humidity(temperature_c: float, relative_humidity_pct: float) -> float:
    """Absolute humidity, in grams of water per cubic metre of air.

    Unlike relative humidity this is conserved as air warms and cools, so it is
    the right quantity for comparing indoor and outdoor air, or one room with
    another.
    """
    ea = actual_vapour_pressure(temperature_c, relative_humidity_pct)
    return (_AH_COEFF * ea) / (temperature_c + 273.15)


def relative_humidity_from_dew_point(
    temperature_c: float, dew_point_c: float
) -> float:
    """Relative humidity in percent, from air temperature and dew point.

    The inverse of :func:`dew_point`. Present so that sensors reporting dew
    point instead of RH can be normalised into the same channel shape.
    """
    if dew_point_c > temperature_c:
        raise ValueError("dew point cannot exceed air temperature")
    ratio = saturation_vapour_pressure(dew_point_c) / saturation_vapour_pressure(
        temperature_c
    )
    return 100.0 * ratio


def lux_to_ppfd(lux: float, lux_per_ppfd: float = SUNLIGHT_LUX_PER_PPFD) -> float:
    """Convert illuminance (lux) to photosynthetic photon flux density.

    Returns micromoles of photons per square metre per second.

    The conversion factor is spectrum-dependent and this is therefore an
    estimate, not a measurement. Record which factor was used alongside any
    derived DLI figure so it can be recomputed if the fixture changes.
    """
    if lux < 0.0:
        raise ValueError("lux cannot be negative")
    if lux_per_ppfd <= 0.0:
        raise ValueError("lux_per_ppfd must be positive")
    return lux / lux_per_ppfd


def dli_increment(ppfd: float, seconds: float) -> float:
    """Daily light integral contributed by `seconds` at a given PPFD.

    Returns moles of photons per square metre. DLI is the sum of these
    increments across a day, conventionally expressed in mol/m2/day.
    """
    if seconds < 0.0:
        raise ValueError("seconds cannot be negative")
    if ppfd < 0.0:
        raise ValueError("ppfd cannot be negative")
    return (ppfd * seconds) / 1_000_000.0


def pressure_to_altitude(
    pressure_kpa: float, sea_level_kpa: float = _SEA_LEVEL_KPA
) -> float:
    """Approximate altitude in metres from barometric pressure.

    Standard-atmosphere approximation. Accurate enough to notice that a sensor
    moved between floors, and nowhere near accurate enough for anything else --
    weather alone moves the apparent altitude by tens of metres.
    """
    if pressure_kpa <= 0.0 or sea_level_kpa <= 0.0:
        raise ValueError("pressures must be positive")
    return _ALTITUDE_COEFF * (
        1.0 - (pressure_kpa / sea_level_kpa) ** _ALTITUDE_EXPONENT
    )


@dataclass(frozen=True, slots=True)
class DliAccumulator:
    """Running daily light integral for one light channel.

    Immutable: :meth:`observe` returns a new accumulator rather than mutating,
    so the control loop can hold one per plant in a plain dict without any
    aliasing surprises, and tests can replay a day deterministically.

    The accumulator is deliberately ignorant of *why* light arrived -- daylight
    through a window and output from a grow lamp both count, which is the whole
    point of targeting an integral rather than switching on a threshold.
    """

    moles: float = 0.0
    last_at: datetime | None = None
    local_day: str | None = None

    def observe(
        self, ppfd: float, at: datetime, local_day: str, max_gap_seconds: float = 300.0
    ) -> DliAccumulator:
        """Fold one PPFD sample in, using trapezoidal time weighting.

        `local_day` is an opaque day key (an ISO date in the zone's local
        timezone). When it changes the accumulator resets, which is how
        midnight rollover happens without this module needing to know anything
        about timezones.

        `max_gap_seconds` guards against a restart or a stalled sensor being
        integrated as though the light had been steady across the whole gap.
        A longer gap contributes nothing and simply re-anchors the clock.
        """
        if ppfd < 0.0:
            raise ValueError("ppfd cannot be negative")
        if at.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")

        if local_day != self.local_day:
            return replace(self, moles=0.0, last_at=at, local_day=local_day)

        if self.last_at is None:
            return replace(self, last_at=at, local_day=local_day)

        elapsed = (at - self.last_at).total_seconds()
        if elapsed <= 0.0 or elapsed > max_gap_seconds:
            return replace(self, last_at=at, local_day=local_day)

        return replace(
            self,
            moles=self.moles + dli_increment(ppfd, elapsed),
            last_at=at,
            local_day=local_day,
        )

    def shortfall(self, target_moles: float) -> float:
        """Moles still needed to reach `target_moles` today. Never negative."""
        return max(0.0, target_moles - self.moles)

    def seconds_of_supplement_needed(
        self, target_moles: float, fixture_ppfd: float
    ) -> float:
        """Seconds a fixture at `fixture_ppfd` must run to close the shortfall.

        Returns 0.0 when the target is already met. Raises if the fixture PPFD
        is not positive, since an unlit fixture can never close a gap and a
        caller asking is confused about something.
        """
        if fixture_ppfd <= 0.0:
            raise ValueError("fixture_ppfd must be positive")
        gap = self.shortfall(target_moles)
        if gap <= 0.0:
            return 0.0
        return (gap * 1_000_000.0) / fixture_ppfd


def _check_humidity(relative_humidity_pct: float) -> None:
    if not 0.0 <= relative_humidity_pct <= 100.0:
        raise ValueError(
            f"relative humidity must be 0-100%, got {relative_humidity_pct}"
        )

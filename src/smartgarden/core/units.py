"""Unit conversion and display formatting.

Storage and computation are always SI (UI-5). These helpers exist for the
display boundary only -- nothing in the control path should call them.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "TemperatureUnit",
    "celsius_to_fahrenheit",
    "fahrenheit_to_celsius",
    "format_duration",
    "format_temperature",
    "hpa_to_kpa",
    "kpa_to_hpa",
]


class TemperatureUnit(StrEnum):
    CELSIUS = "C"
    FAHRENHEIT = "F"


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def kpa_to_hpa(kpa: float) -> float:
    """Kilopascals to hectopascals (millibars).

    Sensor libraries commonly report pressure in hPa while the vapour-pressure
    formulae work in kPa. Converting at the boundary rather than mixing units
    mid-calculation avoids a whole family of factor-of-ten bugs.
    """
    return kpa * 10.0


def hpa_to_kpa(hpa: float) -> float:
    return hpa / 10.0


def format_temperature(
    celsius: float, unit: TemperatureUnit = TemperatureUnit.CELSIUS, digits: int = 1
) -> str:
    if unit is TemperatureUnit.FAHRENHEIT:
        return f"{celsius_to_fahrenheit(celsius):.{digits}f}°F"
    return f"{celsius:.{digits}f}°C"


def format_duration(seconds: float) -> str:
    """Human-readable duration for decision logs and the UI.

    Deliberately terse: these appear inline in sentences like
    "watered 6.5s" or "blocked, 2h 14m until window opens".
    """
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    if seconds < 60:
        return f"{seconds:.1f}s".replace(".0s", "s")

    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not days and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts)

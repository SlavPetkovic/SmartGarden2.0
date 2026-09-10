"""Importing this package registers every actuator driver it contains.

See `smartgarden.drivers.sensors` for why this file exists and does nothing
but import.
"""

from __future__ import annotations

from smartgarden.drivers.actuators import simulated  # noqa: F401

__all__: list[str] = []

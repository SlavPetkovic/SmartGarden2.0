"""Importing this package registers every sensor driver it contains.

This is the one place sensor driver *modules* are named. It says nothing
about what each one implements or which config value selects it -- that is
what `smartgarden.drivers.registry` is for (SENS-1).
"""

from __future__ import annotations

from smartgarden.drivers.sensors import (  # noqa: F401
    bme680,
    seesaw_soil,
    simulated,
    veml7700,
)

__all__: list[str] = []

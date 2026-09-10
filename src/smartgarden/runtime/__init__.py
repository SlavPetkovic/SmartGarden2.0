"""Layer 4: the control service.

Layer 04a (this module, so far) is observe-only: it reads, stores, and
reasons out loud, with no actuation path at all. Layer 04b adds guards,
rules, the watchdog and panic-off, only after the soak (stage B) has set
real moisture thresholds -- see docs/BUILD-PLAN.md.
"""

from __future__ import annotations

from smartgarden.runtime.loop import ControlLoop, SensorBinding
from smartgarden.runtime.wiring import build_control_loop, build_driver

__all__ = ["ControlLoop", "SensorBinding", "build_control_loop", "build_driver"]

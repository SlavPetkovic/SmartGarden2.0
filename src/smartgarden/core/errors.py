"""Exception hierarchy.

One root so callers can catch everything the application raises without also
swallowing genuine programming errors. The control loop distinguishes
`TransientError` (retry, keep going) from everything else (log loudly, and for
a `SafetyError`, refuse to act).
"""

from __future__ import annotations

__all__ = [
    "SmartGardenError",
    "ConfigError",
    "TransientError",
    "SensorError",
    "ActuatorError",
    "SafetyError",
    "StorageError",
]


class SmartGardenError(Exception):
    """Root of every error this application raises deliberately."""


class ConfigError(SmartGardenError):
    """Configuration is invalid or inconsistent.

    Always fatal at startup. A config error must never fall back to a default,
    because the default might water something (OPS-3).
    """


class TransientError(SmartGardenError):
    """A failure that is worth retrying: an I2C blip, a busy bus, a timeout."""


class SensorError(SmartGardenError):
    """A sensor could not be read and retrying did not help."""


class ActuatorError(SmartGardenError):
    """An output could not be driven to the requested state."""


class SafetyError(SmartGardenError):
    """A safety invariant was violated.

    Raised when code attempts something the safety layer must never permit --
    a guard trying to lengthen an actuation, a duration exceeding a device's
    hard limit. These indicate a bug rather than a condition, and are surfaced
    rather than handled.
    """


class StorageError(SmartGardenError):
    """The database could not be read or written."""

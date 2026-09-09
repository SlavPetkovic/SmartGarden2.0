"""Core domain types.

Frozen dataclasses and enums shared by every layer. This module performs no
I/O, imports nothing from `drivers`, `storage` or `web`, and depends on nothing
outside the standard library -- see ARCH-4 in docs/architecture.html.

The shapes here are the contract between layers. Storage serialises them,
drivers produce them, the control loop reasons over them, and the API renders
them. Changing one is a cross-cutting change and should be deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "ActionKind",
    "Actuation",
    "ChannelRole",
    "ChannelSpec",
    "Command",
    "CommandKind",
    "Decision",
    "DecisionKind",
    "DeviceSpec",
    "DeviceState",
    "NodeHealth",
    "Observation",
    "PlantProfile",
    "Quality",
    "Reading",
    "Sample",
    "Zone",
]


class ChannelRole(StrEnum):
    """What a channel *means* to the control logic.

    Rules bind to roles, never to driver names or field names (DATA-3). Swapping
    a Seesaw for a different soil sensor, or moving it to another multiplexer
    channel, leaves every rule untouched because the role is unchanged.

    A channel with no role is still recorded and charted; it just cannot drive a
    decision. That is the correct default for anything not yet trusted.
    """

    SOIL_MOISTURE = "soil_moisture"
    SOIL_TEMP = "soil_temp"
    AIR_TEMP = "air_temp"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    LIGHT = "light"
    GAS_RESISTANCE = "gas_resistance"

    # Derived channels, computed rather than measured. Stored exactly like a
    # measured channel so that downstream code -- and Phase 2 model fitting --
    # cannot tell the difference and does not need to.
    VPD = "vpd"
    DEW_POINT = "dew_point"
    ABSOLUTE_HUMIDITY = "absolute_humidity"
    PPFD = "ppfd"


class Quality(StrEnum):
    """Trustworthiness of a single sample (DATA-6).

    Suspect samples are stored, not discarded. Deleting data at collection time
    destroys the record of what the sensor actually did, which is exactly what
    is needed to diagnose a failing sensor later, and lets a bad sample be
    excluded at model-fit time instead.
    """

    OK = "ok"
    OUT_OF_RANGE = "out_of_range"  # outside the channel's declared plausible band
    RETRIED = "retried"  # succeeded, but not on the first attempt
    STALE = "stale"  # carried forward from an older read
    DERIVED = "derived"  # computed from other channels, not measured


class ActionKind(StrEnum):
    IRRIGATE = "irrigate"
    LIGHT = "light"


class DeviceState(StrEnum):
    ON = "on"
    OFF = "off"


class DecisionKind(StrEnum):
    """Outcome of one control evaluation.

    BLOCKED is distinct from NO_ACTION on purpose: "the plant was thirsty and a
    guard stopped me" and "the plant was fine" look identical in a boolean and
    are completely different when something has gone wrong.
    """

    ACT = "act"
    NO_ACTION = "no_action"
    BLOCKED = "blocked"
    INSUFFICIENT_DATA = "insufficient_data"


class CommandKind(StrEnum):
    """Manual instructions queued by the API for the control loop (ARCH-3)."""

    WATER_NOW = "water_now"
    LIGHT_ON = "light_on"
    LIGHT_OFF = "light_off"
    PAUSE_AUTOMATION = "pause_automation"
    RESUME_AUTOMATION = "resume_automation"
    STOP_ALL = "stop_all"


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """A driver's declaration of one measurement it produces (DATA-2).

    Everything downstream is generated from these: the channel rows in the
    database, the units in the API, the axis labels in the UI. A driver author
    writes this once and touches nothing else (SCOPE-3).
    """

    key: str
    unit: str
    role: ChannelRole | None = None
    precision: int = 2
    plausible_min: float | None = None
    plausible_max: float | None = None
    description: str = ""

    def classify(self, value: float) -> Quality:
        """Grade a raw value against this channel's plausible band."""
        if self.plausible_min is not None and value < self.plausible_min:
            return Quality.OUT_OF_RANGE
        if self.plausible_max is not None and value > self.plausible_max:
            return Quality.OUT_OF_RANGE
        return Quality.OK

    def round(self, value: float) -> float:
        return round(value, self.precision)


@dataclass(frozen=True, slots=True)
class Sample:
    """One value emitted by a driver, before it is bound to a stored channel."""

    key: str
    value: float
    quality: Quality = Quality.OK


@dataclass(frozen=True, slots=True)
class Reading:
    """One stored measurement: a channel, a moment, a number (DATA-1).

    Narrow by design. No measurement ever becomes a table column, which is what
    makes adding a sensor a config change rather than a migration.
    """

    channel_id: int
    at: datetime
    value: float
    quality: Quality = Quality.OK

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("Reading.at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PlantProfile:
    """Care targets for one plant (DATA-5).

    Any field left as None inherits the zone default. This is what lets a
    thirsty fern and a neglect-tolerant succulent share a zone's schedule while
    keeping their own thresholds.
    """

    moisture_low: float | None = None
    moisture_high: float | None = None
    dli_target_moles: float | None = None
    photoperiod_start_hour: int | None = None
    photoperiod_end_hour: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        lo, hi = self.moisture_low, self.moisture_high
        if lo is not None and hi is not None and lo >= hi:
            raise ValueError(
                f"moisture_low ({lo}) must be below moisture_high ({hi}); "
                "a single threshold oscillates, which is why the band exists"
            )
        for hour in (self.photoperiod_start_hour, self.photoperiod_end_hour):
            if hour is not None and not 0 <= hour <= 23:
                raise ValueError(f"photoperiod hours must be 0-23, got {hour}")


@dataclass(frozen=True, slots=True)
class Plant:
    slug: str
    name: str
    zone: str
    species: str = ""
    location: str = ""
    profile: PlantProfile = field(default_factory=PlantProfile)


@dataclass(frozen=True, slots=True)
class Zone:
    """An independently irrigated area, and the safety envelope around it."""

    slug: str
    name: str
    timezone: str = "America/New_York"
    watering_start_hour: int = 7
    watering_end_hour: int = 21
    daily_budget_seconds: float = 120.0
    max_pulses_per_hour: int = 6
    cooldown_seconds: float = 900.0
    settle_seconds: float = 600.0
    enabled: bool = True

    def __post_init__(self) -> None:
        for name, hour in (
            ("watering_start_hour", self.watering_start_hour),
            ("watering_end_hour", self.watering_end_hour),
        ):
            if not 0 <= hour <= 23:
                raise ValueError(f"{name} must be 0-23, got {hour}")
        if self.daily_budget_seconds < 0:
            raise ValueError("daily_budget_seconds cannot be negative")
        if self.max_pulses_per_hour < 0:
            raise ValueError("max_pulses_per_hour cannot be negative")


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    """An output the system can switch, and its own hard limit (SAFE-2).

    `max_on_seconds` is enforced inside the driver regardless of what the caller
    asks for. It is the last line of defence that still lives in the process;
    the watchdog and the systemd stop hook sit outside it.
    """

    slug: str
    kind: ActionKind
    zone: str
    pin: int
    active_low: bool = True
    max_on_seconds: float = 30.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.max_on_seconds <= 0:
            raise ValueError("max_on_seconds must be positive")
        if not 0 <= self.pin <= 27:
            raise ValueError(f"BCM pin must be 0-27, got {self.pin}")


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything the control loop knows about one zone at one instant.

    Assembled from the latest reading per role. Passing this single object into
    the rules keeps them pure and trivially testable: construct one by hand and
    assert on the decision.
    """

    zone: str
    at: datetime
    values: dict[ChannelRole, float] = field(default_factory=dict)
    stale_roles: frozenset[ChannelRole] = frozenset()

    def get(self, role: ChannelRole) -> float | None:
        """Latest fresh value for a role, or None if missing or stale.

        Stale values are deliberately invisible here. A rule that acts on an
        hour-old moisture reading is worse than one that declines to act.
        """
        if role in self.stale_roles:
            return None
        return self.values.get(role)

    def has(self, *roles: ChannelRole) -> bool:
        return all(self.get(role) is not None for role in roles)


@dataclass(frozen=True, slots=True)
class Decision:
    """What the system chose to do, and why (CTRL-8).

    `reason` is written for a human reading the decision log on a phone, not for
    a developer with the source open. "Soil 412 below low threshold 450" beats
    "rule_1 fired".
    """

    at: datetime
    zone: str
    kind: DecisionKind
    action: ActionKind | None = None
    duration_seconds: float | None = None
    reason: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind is DecisionKind.ACT and self.action is None:
            raise ValueError("an ACT decision must name an action")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive when present")


@dataclass(frozen=True, slots=True)
class Actuation:
    """A record of hardware actually being driven (CTRL-9, ML-3).

    Commanded and actual duration are separate fields because they diverge --
    a watchdog force-off, a clamp, a crash mid-pulse. The difference is the
    signal that something is wrong, and it is invisible if only one is stored.

    `post_value` is filled in after the settling window, which is what turns
    this row into a labelled training example rather than just a log line.
    """

    at: datetime
    zone: str
    device: str
    action: ActionKind
    state: DeviceState
    commanded_seconds: float | None = None
    actual_seconds: float | None = None
    pre_value: float | None = None
    post_value: float | None = None
    post_at: datetime | None = None
    reason: str = ""
    forced_off: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def response(self) -> float | None:
        """Observed change across the settling window, if both ends are known."""
        if self.pre_value is None or self.post_value is None:
            return None
        return self.post_value - self.pre_value


@dataclass(frozen=True, slots=True)
class Command:
    """A manual instruction queued for the control loop (ARCH-3).

    Manual actions go through the same guards as automatic ones. A "water now"
    button that bypasses the daily budget is not a convenience, it is a bug with
    a nice icon.
    """

    id: int
    at: datetime
    kind: CommandKind
    zone: str | None = None
    duration_seconds: float | None = None
    issued_by: str = "ui"
    consumed_at: datetime | None = None

    @property
    def pending(self) -> bool:
        return self.consumed_at is None


@dataclass(frozen=True, slots=True)
class NodeHealth:
    """Liveness of one source of readings (DATA-4).

    A node that has gone quiet must read as offline rather than as unchanged.
    The failure mode this prevents: a dead sensor's last value sitting on the
    dashboard looking perfectly healthy while the plant dries out.
    """

    node: str
    last_seen_at: datetime | None
    stale_after_seconds: float
    consecutive_failures: int = 0

    def is_stale(self, now: datetime) -> bool:
        if self.last_seen_at is None:
            return True
        return (now - self.last_seen_at).total_seconds() > self.stale_after_seconds

"""Validated configuration schema.

Hardware topology lives in TOML under git; tuning lives in the database and is
editable from the UI (see §10 of docs/architecture.html). This module covers the
TOML half.

Standard library only, deliberately. The control service is the safety-critical
process and runs unattended for months; every dependency it carries is a thing
that can break on an unattended upgrade. Validation here is explicit rather than
declarative -- more lines, but no reflection, no magic, and error messages
written for someone reading them on a phone at 3am.

Validation is strict and total: unknown keys are rejected rather than ignored,
because a typo'd key that silently does nothing is how a safety limit ends up
not applying (OPS-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from smartgarden.core.errors import ConfigError
from smartgarden.core.models import (
    ActionKind,
    ChannelRole,
    DeviceSpec,
    Plant,
    PlantProfile,
    Zone,
)

__all__ = [
    "AppConfig",
    "Config",
    "DeviceConfig",
    "NodeConfig",
    "PlantConfig",
    "SensorConfig",
    "ZoneConfig",
]


# ---------------------------------------------------------------------------
# field readers
#
# Each takes the raw TOML table and returns a typed value, raising ConfigError
# with a location the reader can act on. TOML has no float/int distinction at
# the syntax level people actually write (`120` is an int), so numeric readers
# accept both and normalise.
# ---------------------------------------------------------------------------


class _Table:
    """A TOML table being read, tracking which keys have been consumed."""

    def __init__(self, raw: Any, where: str) -> None:
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: expected a table, got {type(raw).__name__}")
        self.raw: dict[str, Any] = raw
        self.where = where
        self._seen: set[str] = set()

    # -- readers -----------------------------------------------------------

    def str_(self, key: str, default: str | None = None) -> str:
        value = self._get(key, default)
        if not isinstance(value, str):
            raise ConfigError(f"{self.where}.{key}: expected text, got {value!r}")
        return value

    def bool_(self, key: str, default: bool) -> bool:
        value = self._get(key, default)
        if not isinstance(value, bool):
            raise ConfigError(
                f"{self.where}.{key}: expected true or false, got {value!r}"
            )
        return value

    def int_(
        self,
        key: str,
        default: int | None = None,
        *,
        lo: int | None = None,
        hi: int | None = None,
    ) -> int:
        value = self._get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(
                f"{self.where}.{key}: expected a whole number, got {value!r}"
            )
        self._range(key, value, lo, hi)
        return value

    def float_(
        self,
        key: str,
        default: float | None = None,
        *,
        lo: float | None = None,
        hi: float | None = None,
        exclusive_lo: bool = False,
    ) -> float:
        value = self._get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{self.where}.{key}: expected a number, got {value!r}")
        number = float(value)
        if exclusive_lo and lo is not None and number <= lo:
            raise ConfigError(
                f"{self.where}.{key}: must be greater than {lo}, got {number}"
            )
        self._range(key, number, None if exclusive_lo else lo, hi)
        return number

    def opt_float(
        self, key: str, *, lo: float | None = None, exclusive_lo: bool = False
    ) -> float | None:
        if key not in self.raw:
            self._seen.add(key)
            return None
        return self.float_(key, lo=lo, exclusive_lo=exclusive_lo)

    def opt_int(
        self, key: str, *, lo: int | None = None, hi: int | None = None
    ) -> int | None:
        if key not in self.raw:
            self._seen.add(key)
            return None
        return self.int_(key, lo=lo, hi=hi)

    def opt_str(self, key: str) -> str | None:
        if key not in self.raw:
            self._seen.add(key)
            return None
        return self.str_(key)

    def roles(self, key: str) -> dict[str, ChannelRole]:
        self._seen.add(key)
        raw = self.raw.get(key, {})
        if not isinstance(raw, dict):
            raise ConfigError(f"{self.where}.{key}: expected a table of channel -> role")
        mapping: dict[str, ChannelRole] = {}
        for channel, role_name in raw.items():
            try:
                mapping[channel] = ChannelRole(role_name)
            except ValueError:
                known = ", ".join(sorted(r.value for r in ChannelRole))
                raise ConfigError(
                    f"{self.where}.{key}.{channel}: '{role_name}' is not a known role. "
                    f"Known roles: {known}"
                ) from None
        return mapping

    def action_kind(self, key: str) -> ActionKind:
        raw = self.str_(key)
        try:
            return ActionKind(raw)
        except ValueError:
            known = ", ".join(sorted(k.value for k in ActionKind))
            raise ConfigError(
                f"{self.where}.{key}: '{raw}' is not a known kind. Known kinds: {known}"
            ) from None

    # -- bookkeeping -------------------------------------------------------

    def done(self) -> None:
        """Reject any key not consumed by a reader above."""
        unknown = set(self.raw) - self._seen
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ConfigError(
                f"{self.where}: unknown key(s): {names}. "
                "Extra keys are rejected because a typo that silently does nothing "
                "is how a safety limit stops applying."
            )

    def _get(self, key: str, default: Any) -> Any:
        self._seen.add(key)
        if key in self.raw:
            return self.raw[key]
        if default is None:
            raise ConfigError(f"{self.where}: required key '{key}' is missing")
        return default

    def _range(self, key: str, value: float, lo: float | None, hi: float | None) -> None:
        if lo is not None and value < lo:
            raise ConfigError(f"{self.where}.{key}: must be at least {lo}, got {value}")
        if hi is not None and value > hi:
            raise ConfigError(f"{self.where}.{key}: must be at most {hi}, got {value}")


# ---------------------------------------------------------------------------
# app.toml
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime settings that are not hardware and not per-plant tuning."""

    database_path: str = "data/smartgarden.db"
    backup_dir: str = "data/backups"
    backup_keep: int = 7
    tick_seconds: float = 10.0
    log_level: str = "INFO"
    raw_retention_days: int = 7
    minute_retention_days: int = 90
    automation_enabled: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    # None disables token auth entirely (API-4's "disabled by default"). A
    # non-empty string enables it -- there is no separate on/off flag,
    # because a token that is set but "disabled" is exactly the kind of
    # foot-gun OPS-3 exists to avoid.
    api_token: str | None = None

    def __post_init__(self) -> None:
        if self.minute_retention_days < self.raw_retention_days:
            raise ConfigError(
                "app.toml: minute_retention_days must be at least raw_retention_days, "
                "otherwise history disappears when raw data is pruned"
            )
        if self.api_token is not None and not self.api_token.strip():
            raise ConfigError(
                "app.toml: api_token is set but blank -- omit it to disable auth, "
                "or give it a real value"
            )

    @classmethod
    def parse(cls, raw: Any) -> AppConfig:
        t = _Table(raw, "app.toml [app]")
        config = cls(
            database_path=t.str_("database_path", "data/smartgarden.db"),
            backup_dir=t.str_("backup_dir", "data/backups"),
            backup_keep=t.int_("backup_keep", 7, lo=1),
            tick_seconds=t.float_("tick_seconds", 10.0, lo=0.0, exclusive_lo=True),
            log_level=t.str_("log_level", "INFO"),
            raw_retention_days=t.int_("raw_retention_days", 7, lo=1),
            minute_retention_days=t.int_("minute_retention_days", 90, lo=1),
            automation_enabled=t.bool_("automation_enabled", False),
            web_host=t.str_("web_host", "127.0.0.1"),
            web_port=t.int_("web_port", 8000, lo=1, hi=65535),
            api_token=t.opt_str("api_token"),
        )
        t.done()
        return config


# ---------------------------------------------------------------------------
# sensors.toml
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeConfig:
    """A source of readings: the Pi's own bus, or a remote board.

    Modelling the local bus as a node means a future ESP32 in a garden bed is
    the same kind of thing, not a special case bolted on later (ARCH-6).
    """

    slug: str
    kind: str = "local"
    description: str = ""
    stale_after_seconds: float = 180.0

    def __post_init__(self) -> None:
        if self.kind not in ("local", "remote"):
            raise ConfigError(
                f"node '{self.slug}': kind must be 'local' or 'remote', got '{self.kind}'"
            )

    @classmethod
    def parse(cls, raw: Any, index: int) -> NodeConfig:
        t = _Table(raw, f"sensors.toml [[node]] #{index + 1}")
        node = cls(
            slug=t.str_("slug"),
            kind=t.str_("kind", "local"),
            description=t.str_("description", ""),
            stale_after_seconds=t.float_(
                "stale_after_seconds", 180.0, lo=0.0, exclusive_lo=True
            ),
        )
        t.done()
        return node


@dataclass(frozen=True, slots=True)
class SensorConfig:
    slug: str
    node: str
    driver: str
    address: int | None = None
    mux_address: int | None = None
    mux_channel: int | None = None
    interval_seconds: float = 10.0
    zone: str | None = None
    plant: str | None = None
    enabled: bool = True
    roles: dict[str, ChannelRole] = field(default_factory=dict)
    lux_per_ppfd: float | None = None

    def __post_init__(self) -> None:
        if (self.mux_address is None) != (self.mux_channel is None):
            raise ConfigError(
                f"sensor '{self.slug}': set both mux_address and mux_channel, or neither"
            )

    @property
    def bus_location(self) -> tuple[int | None, int | None, int | None]:
        return (self.address, self.mux_address, self.mux_channel)

    @classmethod
    def parse(cls, raw: Any, index: int) -> SensorConfig:
        t = _Table(raw, f"sensors.toml [[sensor]] #{index + 1}")
        sensor = cls(
            slug=t.str_("slug"),
            node=t.str_("node"),
            driver=t.str_("driver"),
            address=t.opt_int("address", lo=0, hi=0x7F),
            mux_address=t.opt_int("mux_address", lo=0, hi=0x7F),
            mux_channel=t.opt_int("mux_channel", lo=0, hi=7),
            interval_seconds=t.float_(
                "interval_seconds", 10.0, lo=0.0, exclusive_lo=True
            ),
            zone=t.opt_str("zone"),
            plant=t.opt_str("plant"),
            enabled=t.bool_("enabled", True),
            roles=t.roles("roles"),
            lux_per_ppfd=t.opt_float("lux_per_ppfd", lo=0.0, exclusive_lo=True),
        )
        t.done()
        return sensor


# ---------------------------------------------------------------------------
# devices.toml
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZoneConfig:
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

    @classmethod
    def parse(cls, raw: Any, index: int) -> ZoneConfig:
        t = _Table(raw, f"devices.toml [[zone]] #{index + 1}")
        zone = cls(
            slug=t.str_("slug"),
            name=t.str_("name"),
            timezone=t.str_("timezone", "America/New_York"),
            watering_start_hour=t.int_("watering_start_hour", 7, lo=0, hi=23),
            watering_end_hour=t.int_("watering_end_hour", 21, lo=0, hi=23),
            daily_budget_seconds=t.float_("daily_budget_seconds", 120.0, lo=0.0),
            max_pulses_per_hour=t.int_("max_pulses_per_hour", 6, lo=0),
            cooldown_seconds=t.float_("cooldown_seconds", 900.0, lo=0.0),
            settle_seconds=t.float_("settle_seconds", 600.0, lo=0.0),
            enabled=t.bool_("enabled", True),
        )
        t.done()
        return zone

    def to_core(self) -> Zone:
        return Zone(
            slug=self.slug,
            name=self.name,
            timezone=self.timezone,
            watering_start_hour=self.watering_start_hour,
            watering_end_hour=self.watering_end_hour,
            daily_budget_seconds=self.daily_budget_seconds,
            max_pulses_per_hour=self.max_pulses_per_hour,
            cooldown_seconds=self.cooldown_seconds,
            settle_seconds=self.settle_seconds,
            enabled=self.enabled,
        )


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    slug: str
    kind: ActionKind
    zone: str
    driver: str = "simulated"
    pin: int = 0
    active_low: bool = True
    max_on_seconds: float = 30.0
    enabled: bool = True
    pulse_seconds: float = 6.0
    fixture_ppfd: float | None = None

    def __post_init__(self) -> None:
        if self.kind is ActionKind.IRRIGATE and self.pulse_seconds > self.max_on_seconds:
            raise ConfigError(
                f"device '{self.slug}': pulse_seconds ({self.pulse_seconds}) exceeds "
                f"max_on_seconds ({self.max_on_seconds}). The device's hard limit would "
                "clamp every pulse, which is not what you meant."
            )
        if self.kind is ActionKind.LIGHT and self.fixture_ppfd is None:
            raise ConfigError(
                f"device '{self.slug}': a light needs fixture_ppfd, otherwise a daily "
                "light integral shortfall cannot be converted into a run time."
            )

    @classmethod
    def parse(cls, raw: Any, index: int) -> DeviceConfig:
        t = _Table(raw, f"devices.toml [[device]] #{index + 1}")
        device = cls(
            slug=t.str_("slug"),
            kind=t.action_kind("kind"),
            zone=t.str_("zone"),
            driver=t.str_("driver", "simulated"),
            pin=t.int_("pin", 0, lo=0, hi=27),
            active_low=t.bool_("active_low", True),
            max_on_seconds=t.float_("max_on_seconds", 30.0, lo=0.0, exclusive_lo=True),
            enabled=t.bool_("enabled", True),
            pulse_seconds=t.float_("pulse_seconds", 6.0, lo=0.0, exclusive_lo=True),
            fixture_ppfd=t.opt_float("fixture_ppfd", lo=0.0, exclusive_lo=True),
        )
        t.done()
        return device

    def to_core(self) -> DeviceSpec:
        return DeviceSpec(
            slug=self.slug,
            kind=self.kind,
            zone=self.zone,
            pin=self.pin,
            active_low=self.active_low,
            max_on_seconds=self.max_on_seconds,
            enabled=self.enabled,
        )


# ---------------------------------------------------------------------------
# plants.toml
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlantConfig:
    """Seed definition for a plant.

    These are starting values. Once running, thresholds and targets are edited
    through the UI and stored in the database, which takes precedence (UI-3).
    """

    slug: str
    name: str
    zone: str
    species: str = ""
    location: str = ""
    moisture_low: float | None = None
    moisture_high: float | None = None
    dli_target_moles: float | None = None
    photoperiod_start_hour: int | None = None
    photoperiod_end_hour: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        lo, hi = self.moisture_low, self.moisture_high
        if lo is not None and hi is not None and lo >= hi:
            raise ConfigError(
                f"plant '{self.slug}': moisture_low ({lo}) must be below "
                f"moisture_high ({hi}); a single threshold oscillates, which is why "
                "the band exists"
            )

    @classmethod
    def parse(cls, raw: Any, index: int) -> PlantConfig:
        t = _Table(raw, f"plants.toml [[plant]] #{index + 1}")
        plant = cls(
            slug=t.str_("slug"),
            name=t.str_("name"),
            zone=t.str_("zone"),
            species=t.str_("species", ""),
            location=t.str_("location", ""),
            moisture_low=t.opt_float("moisture_low"),
            moisture_high=t.opt_float("moisture_high"),
            dli_target_moles=t.opt_float("dli_target_moles", lo=0.0, exclusive_lo=True),
            photoperiod_start_hour=t.opt_int("photoperiod_start_hour", lo=0, hi=23),
            photoperiod_end_hour=t.opt_int("photoperiod_end_hour", lo=0, hi=23),
            notes=t.str_("notes", ""),
        )
        t.done()
        return plant

    def to_core(self) -> Plant:
        return Plant(
            slug=self.slug,
            name=self.name,
            zone=self.zone,
            species=self.species,
            location=self.location,
            profile=PlantProfile(
                moisture_low=self.moisture_low,
                moisture_high=self.moisture_high,
                dli_target_moles=self.dli_target_moles,
                photoperiod_start_hour=self.photoperiod_start_hour,
                photoperiod_end_hour=self.photoperiod_end_hour,
                notes=self.notes,
            ),
        )


# ---------------------------------------------------------------------------
# assembled
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Config:
    """The whole validated configuration, with cross-references checked.

    Individual sections validate in isolation; the interesting failures are
    between them -- a sensor pointing at a node that does not exist, two devices
    sharing a GPIO pin, two sensors at the same bus address. Those are caught
    here, at startup, rather than at 3am.
    """

    app: AppConfig
    nodes: tuple[NodeConfig, ...] = ()
    sensors: tuple[SensorConfig, ...] = ()
    zones: tuple[ZoneConfig, ...] = ()
    devices: tuple[DeviceConfig, ...] = ()
    plants: tuple[PlantConfig, ...] = ()

    def __post_init__(self) -> None:
        _reject_duplicates("node", [n.slug for n in self.nodes])
        _reject_duplicates("sensor", [s.slug for s in self.sensors])
        _reject_duplicates("zone", [z.slug for z in self.zones])
        _reject_duplicates("device", [d.slug for d in self.devices])
        _reject_duplicates("plant", [p.slug for p in self.plants])

        node_slugs = {n.slug for n in self.nodes}
        zone_slugs = {z.slug for z in self.zones}
        plant_slugs = {p.slug for p in self.plants}

        for sensor in self.sensors:
            if sensor.node not in node_slugs:
                raise ConfigError(
                    f"sensor '{sensor.slug}' refers to unknown node '{sensor.node}'. "
                    f"Known nodes: {', '.join(sorted(node_slugs)) or 'none'}"
                )
            if sensor.zone is not None and sensor.zone not in zone_slugs:
                raise ConfigError(
                    f"sensor '{sensor.slug}' refers to unknown zone '{sensor.zone}'"
                )
            if sensor.plant is not None and sensor.plant not in plant_slugs:
                raise ConfigError(
                    f"sensor '{sensor.slug}' refers to unknown plant '{sensor.plant}'"
                )

        for device in self.devices:
            if device.zone not in zone_slugs:
                raise ConfigError(
                    f"device '{device.slug}' refers to unknown zone '{device.zone}'"
                )

        for plant in self.plants:
            if plant.zone not in zone_slugs:
                raise ConfigError(
                    f"plant '{plant.slug}' refers to unknown zone '{plant.zone}'"
                )

        self._check_pin_conflicts()
        self._check_bus_conflicts()

    def _check_pin_conflicts(self) -> None:
        """Two real devices on one GPIO pin means one silently shadows the other.

        Simulated devices are exempt: they touch no hardware, and forbidding
        overlap would make the no-hardware config tedious to write.
        """
        seen: dict[int, str] = {}
        for device in self.devices:
            if not device.enabled or device.driver == "simulated":
                continue
            if device.pin in seen:
                raise ConfigError(
                    f"devices '{seen[device.pin]}' and '{device.slug}' both use "
                    f"BCM pin {device.pin}"
                )
            seen[device.pin] = device.slug

    def _check_bus_conflicts(self) -> None:
        """Two sensors at one bus location cannot both be read."""
        seen: dict[tuple[int | None, int | None, int | None], str] = {}
        for sensor in self.sensors:
            if not sensor.enabled or sensor.address is None:
                continue
            location = sensor.bus_location
            if location in seen:
                where = f"address 0x{sensor.address:02x}"
                if sensor.mux_channel is not None:
                    where += f" on mux channel {sensor.mux_channel}"
                raise ConfigError(
                    f"sensors '{seen[location]}' and '{sensor.slug}' share {where}. "
                    "Use a different address, or a TCA9548A multiplexer channel."
                )
            seen[location] = sensor.slug

    # -- lookups -----------------------------------------------------------

    def zone(self, slug: str) -> ZoneConfig:
        for zone in self.zones:
            if zone.slug == slug:
                return zone
        raise KeyError(f"no zone '{slug}'")

    def plants_in(self, zone_slug: str) -> tuple[PlantConfig, ...]:
        return tuple(p for p in self.plants if p.zone == zone_slug)

    def devices_in(
        self, zone_slug: str, kind: ActionKind | None = None
    ) -> tuple[DeviceConfig, ...]:
        return tuple(
            d
            for d in self.devices
            if d.zone == zone_slug and (kind is None or d.kind is kind)
        )

    def sensors_on(self, node_slug: str) -> tuple[SensorConfig, ...]:
        return tuple(s for s in self.sensors if s.node == node_slug)


def _reject_duplicates(label: str, slugs: list[str]) -> None:
    seen: set[str] = set()
    for slug in slugs:
        if slug in seen:
            raise ConfigError(f"duplicate {label} slug '{slug}'")
        seen.add(slug)


def _parse_list(raw: Any, parser: Any, section: str) -> tuple[Any, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{section}: expected a list of tables ([[{section}]])")
    return tuple(parser(item, index) for index, item in enumerate(raw))

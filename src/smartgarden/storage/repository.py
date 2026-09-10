"""Row-level access to the database (DATA-1...6, ARCH-3, CTRL-8/9, ML-3).

One `Repository` wraps one open connection. Every method takes and returns
core dataclasses -- `Reading`, `Decision`, `Command`, `Actuation`, `Zone`,
`Plant`, `DeviceSpec`, `ChannelSpec` -- so nothing above this layer names a
column or a table.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smartgarden.core.errors import StorageError
from smartgarden.core.models import (
    ActionKind,
    Actuation,
    ChannelRole,
    ChannelSpec,
    Command,
    CommandKind,
    Decision,
    DecisionKind,
    DeviceSpec,
    DeviceState,
    Plant,
    PlantProfile,
    Quality,
    Reading,
    Zone,
)
from smartgarden.storage.timeutil import from_iso, to_iso

__all__ = ["ChannelInfo", "NodeInfo", "Repository", "RollupPoint", "SensorInfo"]

_SlugTable = Literal["node", "zone", "plant", "device", "sensor"]


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    """Channel metadata for the API's channel-listing endpoint (API-2).

    A new sensor appears here the moment its channels are reconciled --
    nothing about this shape needs to change for a new driver to show up.
    """

    id: int
    sensor: str
    key: str
    unit: str
    role: ChannelRole | None
    precision: int
    plausible_min: float | None
    plausible_max: float | None
    zone: str | None
    plant: str | None


@dataclass(frozen=True, slots=True)
class RollupPoint:
    bucket_start: datetime
    min_value: float
    max_value: float
    mean_value: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class NodeInfo:
    """A node's own metadata, for the API's health view (DATA-4)."""

    slug: str
    kind: str
    description: str
    stale_after_seconds: float
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class SensorInfo:
    """A sensor's wiring, for the health view -- the one place a driver,
    address or mux channel is named (SCOPE-3's own exception for it)."""

    slug: str
    node: str
    driver: str
    address: int | None
    mux_address: int | None
    mux_channel: int | None
    interval_seconds: float
    enabled: bool


def _plant_from_row(row: sqlite3.Row) -> Plant:
    return Plant(
        slug=row["slug"],
        name=row["name"],
        zone=row["zone_slug"],
        species=row["species"],
        location=row["location"],
        profile=PlantProfile(
            moisture_low=row["moisture_low"],
            moisture_high=row["moisture_high"],
            dli_target_moles=row["dli_target_moles"],
            photoperiod_start_hour=row["photoperiod_start_hour"],
            photoperiod_end_hour=row["photoperiod_end_hour"],
            notes=row["notes"],
        ),
    )


def _zone_from_row(row: sqlite3.Row) -> Zone:
    return Zone(
        slug=row["slug"],
        name=row["name"],
        timezone=row["timezone"],
        watering_start_hour=row["watering_start_hour"],
        watering_end_hour=row["watering_end_hour"],
        daily_budget_seconds=row["daily_budget_seconds"],
        max_pulses_per_hour=row["max_pulses_per_hour"],
        cooldown_seconds=row["cooldown_seconds"],
        settle_seconds=row["settle_seconds"],
        enabled=bool(row["enabled"]),
    )


_PLANT_COLUMNS = """
    plant.slug AS slug, plant.name AS name, zone.slug AS zone_slug,
    plant.species AS species, plant.location AS location,
    plant.moisture_low AS moisture_low, plant.moisture_high AS moisture_high,
    plant.dli_target_moles AS dli_target_moles,
    plant.photoperiod_start_hour AS photoperiod_start_hour,
    plant.photoperiod_end_hour AS photoperiod_end_hour,
    plant.notes AS notes
"""

_ZONE_COLUMNS = """
    slug, name, timezone, watering_start_hour, watering_end_hour,
    daily_budget_seconds, max_pulses_per_hour, cooldown_seconds,
    settle_seconds, enabled
"""


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- topology: nodes, zones, plants, devices, sensors, channels --------

    def upsert_node(
        self, slug: str, *, kind: str, stale_after_seconds: float, description: str = ""
    ) -> int:
        self._conn.execute(
            """
            INSERT INTO node (slug, kind, description, stale_after_seconds)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                kind = excluded.kind,
                description = excluded.description,
                stale_after_seconds = excluded.stale_after_seconds
            """,
            (slug, kind, description, stale_after_seconds),
        )
        return self._id("node", slug)

    def touch_node(self, slug: str, at: datetime) -> None:
        self._conn.execute(
            "UPDATE node SET last_seen_at = ? WHERE slug = ?", (to_iso(at), slug)
        )

    def last_seen(self, slug: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_seen_at FROM node WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise StorageError(f"no node with slug {slug!r}")
        return from_iso(row["last_seen_at"]) if row["last_seen_at"] is not None else None

    def upsert_zone(self, zone: Zone) -> int:
        self._conn.execute(
            """
            INSERT INTO zone (
                slug, name, timezone, watering_start_hour, watering_end_hour,
                daily_budget_seconds, max_pulses_per_hour, cooldown_seconds,
                settle_seconds, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                name = excluded.name,
                timezone = excluded.timezone,
                watering_start_hour = excluded.watering_start_hour,
                watering_end_hour = excluded.watering_end_hour,
                daily_budget_seconds = excluded.daily_budget_seconds,
                max_pulses_per_hour = excluded.max_pulses_per_hour,
                cooldown_seconds = excluded.cooldown_seconds,
                settle_seconds = excluded.settle_seconds,
                enabled = excluded.enabled
            """,
            (
                zone.slug,
                zone.name,
                zone.timezone,
                zone.watering_start_hour,
                zone.watering_end_hour,
                zone.daily_budget_seconds,
                zone.max_pulses_per_hour,
                zone.cooldown_seconds,
                zone.settle_seconds,
                int(zone.enabled),
            ),
        )
        return self._id("zone", zone.slug)

    def get_zone(self, slug: str) -> Zone | None:
        row = self._conn.execute(
            f"SELECT {_ZONE_COLUMNS} FROM zone WHERE slug = ?", (slug,)
        ).fetchone()
        return _zone_from_row(row) if row is not None else None

    def all_zones(self) -> list[Zone]:
        rows = self._conn.execute(
            f"SELECT {_ZONE_COLUMNS} FROM zone ORDER BY slug"
        ).fetchall()
        return [_zone_from_row(row) for row in rows]

    def upsert_plant(self, plant: Plant) -> int:
        zone_id = self._id("zone", plant.zone)
        profile = plant.profile
        self._conn.execute(
            """
            INSERT INTO plant (
                slug, name, zone_id, species, location, moisture_low,
                moisture_high, dli_target_moles, photoperiod_start_hour,
                photoperiod_end_hour, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                name = excluded.name,
                zone_id = excluded.zone_id,
                species = excluded.species,
                location = excluded.location,
                moisture_low = excluded.moisture_low,
                moisture_high = excluded.moisture_high,
                dli_target_moles = excluded.dli_target_moles,
                photoperiod_start_hour = excluded.photoperiod_start_hour,
                photoperiod_end_hour = excluded.photoperiod_end_hour,
                notes = excluded.notes
            """,
            (
                plant.slug,
                plant.name,
                zone_id,
                plant.species,
                plant.location,
                profile.moisture_low,
                profile.moisture_high,
                profile.dli_target_moles,
                profile.photoperiod_start_hour,
                profile.photoperiod_end_hour,
                profile.notes,
            ),
        )
        return self._id("plant", plant.slug)

    def get_plant(self, slug: str) -> Plant | None:
        row = self._conn.execute(
            f"""
            SELECT {_PLANT_COLUMNS}
            FROM plant JOIN zone ON zone.id = plant.zone_id
            WHERE plant.slug = ?
            """,
            (slug,),
        ).fetchone()
        return _plant_from_row(row) if row is not None else None

    def all_plants(self) -> list[Plant]:
        rows = self._conn.execute(
            f"""
            SELECT {_PLANT_COLUMNS}
            FROM plant JOIN zone ON zone.id = plant.zone_id
            ORDER BY plant.slug
            """
        ).fetchall()
        return [_plant_from_row(row) for row in rows]

    def upsert_device(self, device: DeviceSpec) -> int:
        zone_id = self._id("zone", device.zone)
        self._conn.execute(
            """
            INSERT INTO device (
                slug, kind, zone_id, pin, active_low, max_on_seconds, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                kind = excluded.kind,
                zone_id = excluded.zone_id,
                pin = excluded.pin,
                active_low = excluded.active_low,
                max_on_seconds = excluded.max_on_seconds,
                enabled = excluded.enabled
            """,
            (
                device.slug,
                device.kind.value,
                zone_id,
                device.pin,
                int(device.active_low),
                device.max_on_seconds,
                int(device.enabled),
            ),
        )
        return self._id("device", device.slug)

    def upsert_sensor(
        self,
        slug: str,
        *,
        node: str,
        driver: str,
        interval_seconds: float,
        address: int | None = None,
        mux_address: int | None = None,
        mux_channel: int | None = None,
        enabled: bool = True,
    ) -> int:
        node_id = self._id("node", node)
        self._conn.execute(
            """
            INSERT INTO sensor (
                slug, node_id, driver, address, mux_address, mux_channel,
                interval_seconds, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                node_id = excluded.node_id,
                driver = excluded.driver,
                address = excluded.address,
                mux_address = excluded.mux_address,
                mux_channel = excluded.mux_channel,
                interval_seconds = excluded.interval_seconds,
                enabled = excluded.enabled
            """,
            (
                slug,
                node_id,
                driver,
                address,
                mux_address,
                mux_channel,
                interval_seconds,
                int(enabled),
            ),
        )
        return self._id("sensor", slug)

    def all_nodes(self) -> list[NodeInfo]:
        """Every node, for the API's health view (DATA-4)."""
        rows = self._conn.execute(
            "SELECT slug, kind, description, stale_after_seconds, last_seen_at "
            "FROM node ORDER BY slug"
        ).fetchall()
        return [
            NodeInfo(
                slug=row["slug"],
                kind=row["kind"],
                description=row["description"],
                stale_after_seconds=row["stale_after_seconds"],
                last_seen_at=from_iso(row["last_seen_at"])
                if row["last_seen_at"] is not None
                else None,
            )
            for row in rows
        ]

    def all_sensors(self) -> list[SensorInfo]:
        """Every sensor's wiring, for the health view (SENS-8)."""
        rows = self._conn.execute(
            """
            SELECT
                sensor.slug AS slug, node.slug AS node, sensor.driver AS driver,
                sensor.address AS address, sensor.mux_address AS mux_address,
                sensor.mux_channel AS mux_channel,
                sensor.interval_seconds AS interval_seconds, sensor.enabled AS enabled
            FROM sensor JOIN node ON node.id = sensor.node_id
            ORDER BY sensor.slug
            """
        ).fetchall()
        return [
            SensorInfo(
                slug=row["slug"],
                node=row["node"],
                driver=row["driver"],
                address=row["address"],
                mux_address=row["mux_address"],
                mux_channel=row["mux_channel"],
                interval_seconds=row["interval_seconds"],
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def reconcile_channels(
        self,
        sensor_slug: str,
        specs: Sequence[ChannelSpec],
        *,
        zone: str | None = None,
        plant: str | None = None,
    ) -> dict[str, int]:
        """Upsert one channel row per declared spec (DATA-2).

        This is the only place a driver's `channels()` declaration turns into
        rows. Nothing else in the codebase enumerates channel keys by hand, so
        adding a sensor is a config change and a driver, never a migration
        (SENS-1, DATA-1).
        """
        sensor_id = self._id("sensor", sensor_slug)
        zone_id = self._id("zone", zone) if zone is not None else None
        plant_id = self._id("plant", plant) if plant is not None else None

        result: dict[str, int] = {}
        for spec in specs:
            self._conn.execute(
                """
                INSERT INTO channel (
                    sensor_id, key, unit, precision, role, plausible_min,
                    plausible_max, zone_id, plant_id, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sensor_id, key) DO UPDATE SET
                    unit = excluded.unit,
                    precision = excluded.precision,
                    role = excluded.role,
                    plausible_min = excluded.plausible_min,
                    plausible_max = excluded.plausible_max,
                    zone_id = excluded.zone_id,
                    plant_id = excluded.plant_id,
                    description = excluded.description
                """,
                (
                    sensor_id,
                    spec.key,
                    spec.unit,
                    spec.precision,
                    spec.role.value if spec.role is not None else None,
                    spec.plausible_min,
                    spec.plausible_max,
                    zone_id,
                    plant_id,
                    spec.description,
                ),
            )
            row = self._conn.execute(
                "SELECT id FROM channel WHERE sensor_id = ? AND key = ?",
                (sensor_id, spec.key),
            ).fetchone()
            result[spec.key] = int(row["id"])
        return result

    def all_channels(self) -> list[ChannelInfo]:
        """Every channel, for the API's metadata endpoint (API-2)."""
        rows = self._conn.execute(
            """
            SELECT
                channel.id AS id, sensor.slug AS sensor, channel.key AS key,
                channel.unit AS unit, channel.role AS role,
                channel.precision AS precision,
                channel.plausible_min AS plausible_min,
                channel.plausible_max AS plausible_max,
                zone.slug AS zone, plant.slug AS plant
            FROM channel
            JOIN sensor ON sensor.id = channel.sensor_id
            LEFT JOIN zone ON zone.id = channel.zone_id
            LEFT JOIN plant ON plant.id = channel.plant_id
            ORDER BY sensor.slug, channel.key
            """
        ).fetchall()
        return [
            ChannelInfo(
                id=int(row["id"]),
                sensor=row["sensor"],
                key=row["key"],
                unit=row["unit"],
                role=ChannelRole(row["role"]) if row["role"] is not None else None,
                precision=int(row["precision"]),
                plausible_min=row["plausible_min"],
                plausible_max=row["plausible_max"],
                zone=row["zone"],
                plant=row["plant"],
            )
            for row in rows
        ]

    # -- readings ------------------------------------------------------------

    def insert_reading(self, reading: Reading) -> int:
        cur = self._conn.execute(
            "INSERT INTO reading (channel_id, ts, value, quality) VALUES (?, ?, ?, ?)",
            (
                reading.channel_id,
                to_iso(reading.at),
                reading.value,
                reading.quality.value,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def insert_readings(self, readings: Iterable[Reading]) -> int:
        rows = [(r.channel_id, to_iso(r.at), r.value, r.quality.value) for r in readings]
        if not rows:
            return 0
        self._conn.executemany(
            "INSERT INTO reading (channel_id, ts, value, quality) VALUES (?, ?, ?, ?)",
            rows,
        )
        return len(rows)

    def readings_between(
        self, channel_id: int, start: datetime, end: datetime
    ) -> list[Reading]:
        rows = self._conn.execute(
            """
            SELECT channel_id, ts, value, quality FROM reading
            WHERE channel_id = ? AND ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (channel_id, to_iso(start), to_iso(end)),
        ).fetchall()
        return [
            Reading(
                channel_id=int(row["channel_id"]),
                at=from_iso(row["ts"]),
                value=float(row["value"]),
                quality=Quality(row["quality"]),
            )
            for row in rows
        ]

    def rollup_between(
        self, channel_id: int, tier: str, start: datetime, end: datetime
    ) -> list[RollupPoint]:
        """Rollup buckets for a channel and tier, for the API's time-series
        endpoint once it has picked a tier coarser than raw (API-3)."""
        rows = self._conn.execute(
            """
            SELECT bucket_start, min_value, max_value, mean_value, sample_count
            FROM reading_rollup
            WHERE channel_id = ? AND tier = ? AND bucket_start >= ? AND bucket_start < ?
            ORDER BY bucket_start
            """,
            (channel_id, tier, to_iso(start), to_iso(end)),
        ).fetchall()
        return [
            RollupPoint(
                bucket_start=from_iso(row["bucket_start"]),
                min_value=float(row["min_value"]),
                max_value=float(row["max_value"]),
                mean_value=float(row["mean_value"]),
                sample_count=int(row["sample_count"]),
            )
            for row in rows
        ]

    def channels_by_role(self, zone_slug: str) -> dict[ChannelRole, int]:
        """The one channel per role bound to a zone (DATA-3).

        Answers "which channel is *the* soil_moisture reading for this
        zone" without the caller ever naming a sensor or driver. If two
        channels in a zone share a role, the last one found wins -- an
        ambiguity that matters once a zone holds more than one plant,
        not before.
        """
        zone_id = self._id("zone", zone_slug)
        rows = self._conn.execute(
            "SELECT id, role FROM channel WHERE zone_id = ? AND role IS NOT NULL",
            (zone_id,),
        ).fetchall()
        return {ChannelRole(row["role"]): int(row["id"]) for row in rows}

    def latest_value(self, channel_id: int) -> tuple[float, datetime] | None:
        """The most recent raw reading for a channel, or None if it has none yet."""
        row = self._conn.execute(
            "SELECT value, ts FROM reading WHERE channel_id = ? ORDER BY ts DESC LIMIT 1",
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        return (float(row["value"]), from_iso(row["ts"]))

    # -- decisions, commands, actuations --------------------------------------

    def insert_decision(self, decision: Decision) -> int:
        zone_id = self._id("zone", decision.zone)
        cur = self._conn.execute(
            """
            INSERT INTO decision (
                ts, zone_id, kind, action, duration_seconds, reason, inputs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_iso(decision.at),
                zone_id,
                decision.kind.value,
                decision.action.value if decision.action is not None else None,
                decision.duration_seconds,
                decision.reason,
                json.dumps(decision.inputs, default=str),
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def recent_decisions(self, zone_slug: str, *, limit: int = 10) -> list[Decision]:
        """The most recent decisions for a zone, newest first (CTRL-8)."""
        zone_id = self._id("zone", zone_slug)
        rows = self._conn.execute(
            """
            SELECT ts, kind, action, duration_seconds, reason, inputs FROM decision
            WHERE zone_id = ? ORDER BY ts DESC, id DESC LIMIT ?
            """,
            (zone_id, limit),
        ).fetchall()
        return [
            Decision(
                at=from_iso(row["ts"]),
                zone=zone_slug,
                kind=DecisionKind(row["kind"]),
                action=ActionKind(row["action"]) if row["action"] is not None else None,
                duration_seconds=row["duration_seconds"],
                reason=row["reason"],
                inputs=json.loads(row["inputs"]),
            )
            for row in rows
        ]

    def insert_command(self, command: Command) -> int:
        zone_id = self._id("zone", command.zone) if command.zone is not None else None
        cur = self._conn.execute(
            """
            INSERT INTO command (
                ts, kind, zone_id, duration_seconds, issued_by, consumed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                to_iso(command.at),
                command.kind.value,
                zone_id,
                command.duration_seconds,
                command.issued_by,
                to_iso(command.consumed_at) if command.consumed_at is not None else None,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def pending_commands(self) -> list[Command]:
        rows = self._conn.execute(
            """
            SELECT command.id AS id, command.ts AS ts, command.kind AS kind,
                   zone.slug AS zone_slug, command.duration_seconds AS duration_seconds,
                   command.issued_by AS issued_by
            FROM command
            LEFT JOIN zone ON zone.id = command.zone_id
            WHERE command.consumed_at IS NULL
            ORDER BY command.ts
            """
        ).fetchall()
        return [
            Command(
                id=int(row["id"]),
                at=from_iso(row["ts"]),
                kind=CommandKind(row["kind"]),
                zone=row["zone_slug"],
                duration_seconds=row["duration_seconds"],
                issued_by=row["issued_by"],
                consumed_at=None,
            )
            for row in rows
        ]

    def consume_command(self, command_id: int, at: datetime) -> None:
        self._conn.execute(
            "UPDATE command SET consumed_at = ? WHERE id = ?", (to_iso(at), command_id)
        )

    def insert_actuation(self, actuation: Actuation) -> int:
        zone_id = self._id("zone", actuation.zone)
        device_id = self._id("device", actuation.device)
        cur = self._conn.execute(
            """
            INSERT INTO actuation (
                ts, zone_id, device_id, action, state, commanded_seconds,
                actual_seconds, pre_value, post_value, post_at, reason,
                forced_off, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_iso(actuation.at),
                zone_id,
                device_id,
                actuation.action.value,
                actuation.state.value,
                actuation.commanded_seconds,
                actuation.actual_seconds,
                actuation.pre_value,
                actuation.post_value,
                to_iso(actuation.post_at) if actuation.post_at is not None else None,
                actuation.reason,
                int(actuation.forced_off),
                json.dumps(actuation.metadata, default=str),
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def actuations_between(
        self, zone_slug: str, start: datetime, end: datetime
    ) -> list[Actuation]:
        """Actuations for a zone in a window (UI-6: marking irrigation events
        on a chart). Empty in stage A, since nothing can act yet -- the read
        path exists now so it needs no further work once layer 04b starts
        writing rows here."""
        zone_id = self._id("zone", zone_slug)
        rows = self._conn.execute(
            """
            SELECT
                actuation.ts AS ts, device.slug AS device, actuation.action AS action,
                actuation.state AS state,
                actuation.commanded_seconds AS commanded_seconds,
                actuation.actual_seconds AS actual_seconds,
                actuation.pre_value AS pre_value,
                actuation.post_value AS post_value, actuation.post_at AS post_at,
                actuation.reason AS reason, actuation.forced_off AS forced_off,
                actuation.metadata AS metadata
            FROM actuation
            JOIN device ON device.id = actuation.device_id
            WHERE actuation.zone_id = ? AND actuation.ts >= ? AND actuation.ts < ?
            ORDER BY actuation.ts
            """,
            (zone_id, to_iso(start), to_iso(end)),
        ).fetchall()
        return [
            Actuation(
                at=from_iso(row["ts"]),
                zone=zone_slug,
                device=row["device"],
                action=ActionKind(row["action"]),
                state=DeviceState(row["state"]),
                commanded_seconds=row["commanded_seconds"],
                actual_seconds=row["actual_seconds"],
                pre_value=row["pre_value"],
                post_value=row["post_value"],
                post_at=from_iso(row["post_at"]) if row["post_at"] is not None else None,
                reason=row["reason"],
                forced_off=bool(row["forced_off"]),
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    # -- lookups ---------------------------------------------------------------

    def _id(self, table: _SlugTable, slug: str) -> int:
        row = self._conn.execute(
            f"SELECT id FROM {table} WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise StorageError(f"no {table} with slug {slug!r}")
        return int(row["id"])

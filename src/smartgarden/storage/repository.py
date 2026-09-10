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
from datetime import datetime
from typing import Literal

from smartgarden.core.errors import StorageError
from smartgarden.core.models import (
    Actuation,
    ChannelSpec,
    Command,
    CommandKind,
    Decision,
    DeviceSpec,
    Plant,
    Quality,
    Reading,
    Zone,
)
from smartgarden.storage.timeutil import from_iso, to_iso

__all__ = ["Repository"]

_SlugTable = Literal["node", "zone", "plant", "device", "sensor"]


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

    # -- lookups ---------------------------------------------------------------

    def _id(self, table: _SlugTable, slug: str) -> int:
        row = self._conn.execute(
            f"SELECT id FROM {table} WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise StorageError(f"no {table} with slug {slug!r}")
        return int(row["id"])

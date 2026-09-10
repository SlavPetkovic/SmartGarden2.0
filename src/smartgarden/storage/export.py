"""Export command: joined CSV for a notebook (STOR-5).

Three files, one per subject -- readings, decisions, actuations -- each
joined against its dimension tables so a name appears instead of a bare
foreign key. `outcomes` from the requirement text is not a fourth file: an
actuation's pre/post values and their difference *are* the outcome of that
actuation, so they are columns on actuations.csv rather than a separate join.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from smartgarden.storage.timeutil import to_iso

__all__ = ["ExportResult", "export_range"]


@dataclass(frozen=True, slots=True)
class ExportResult:
    readings: Path
    decisions: Path
    actuations: Path


def export_range(
    conn: sqlite3.Connection, out_dir: Path, start: datetime, end: datetime
) -> ExportResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    return ExportResult(
        readings=_export_readings(conn, out_dir / "readings.csv", start, end),
        decisions=_export_decisions(conn, out_dir / "decisions.csv", start, end),
        actuations=_export_actuations(conn, out_dir / "actuations.csv", start, end),
    )


def _export_readings(
    conn: sqlite3.Connection, path: Path, start: datetime, end: datetime
) -> Path:
    rows = conn.execute(
        """
        SELECT
            reading.ts AS ts,
            node.slug AS node,
            sensor.slug AS sensor,
            channel.key AS channel,
            channel.role AS role,
            zone.slug AS zone,
            plant.slug AS plant,
            channel.unit AS unit,
            reading.value AS value,
            reading.quality AS quality
        FROM reading
        JOIN channel ON channel.id = reading.channel_id
        JOIN sensor ON sensor.id = channel.sensor_id
        JOIN node ON node.id = sensor.node_id
        LEFT JOIN zone ON zone.id = channel.zone_id
        LEFT JOIN plant ON plant.id = channel.plant_id
        WHERE reading.ts >= ? AND reading.ts < ?
        ORDER BY reading.ts
        """,
        (to_iso(start), to_iso(end)),
    ).fetchall()
    header = [
        "ts",
        "node",
        "sensor",
        "channel",
        "role",
        "zone",
        "plant",
        "unit",
        "value",
        "quality",
    ]
    _write_csv(path, header, rows)
    return path


def _export_decisions(
    conn: sqlite3.Connection, path: Path, start: datetime, end: datetime
) -> Path:
    rows = conn.execute(
        """
        SELECT
            decision.ts AS ts,
            zone.slug AS zone,
            decision.kind AS kind,
            decision.action AS action,
            decision.duration_seconds AS duration_seconds,
            decision.reason AS reason,
            decision.inputs AS inputs
        FROM decision
        JOIN zone ON zone.id = decision.zone_id
        WHERE decision.ts >= ? AND decision.ts < ?
        ORDER BY decision.ts
        """,
        (to_iso(start), to_iso(end)),
    ).fetchall()
    header = ["ts", "zone", "kind", "action", "duration_seconds", "reason", "inputs"]
    _write_csv(path, header, rows)
    return path


def _export_actuations(
    conn: sqlite3.Connection, path: Path, start: datetime, end: datetime
) -> Path:
    rows = conn.execute(
        """
        SELECT
            actuation.ts AS ts,
            zone.slug AS zone,
            device.slug AS device,
            actuation.action AS action,
            actuation.state AS state,
            actuation.commanded_seconds AS commanded_seconds,
            actuation.actual_seconds AS actual_seconds,
            actuation.pre_value AS pre_value,
            actuation.post_value AS post_value,
            CASE
                WHEN actuation.pre_value IS NOT NULL AND actuation.post_value IS NOT NULL
                THEN actuation.post_value - actuation.pre_value
                ELSE NULL
            END AS outcome,
            actuation.post_at AS post_at,
            actuation.reason AS reason,
            actuation.forced_off AS forced_off
        FROM actuation
        JOIN zone ON zone.id = actuation.zone_id
        JOIN device ON device.id = actuation.device_id
        WHERE actuation.ts >= ? AND actuation.ts < ?
        ORDER BY actuation.ts
        """,
        (to_iso(start), to_iso(end)),
    ).fetchall()
    header = [
        "ts",
        "zone",
        "device",
        "action",
        "state",
        "commanded_seconds",
        "actual_seconds",
        "pre_value",
        "post_value",
        "outcome",
        "post_at",
        "reason",
        "forced_off",
    ]
    _write_csv(path, header, rows)
    return path


def _write_csv(path: Path, header: list[str], rows: list[sqlite3.Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row[column] for column in header])

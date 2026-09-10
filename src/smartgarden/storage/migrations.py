"""Numbered SQL migrations, applied in order and recorded (STOR-1).

`migrations/` at the repository root is the one source of schema truth. A file
is named `NNNN_description.sql`; the four-digit prefix is the version number
and the only thing that matters for ordering. Applying the same directory
twice against the same database is a no-op -- that is what a test in
tests/test_storage_migrations.py checks by doing exactly that.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from smartgarden.core.errors import StorageError

__all__ = ["DEFAULT_MIGRATIONS_DIR", "applied_versions", "apply_migrations"]

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
)
"""


def _discover(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    if not migrations_dir.is_dir():
        raise StorageError(f"migrations directory does not exist: {migrations_dir}")

    found: list[tuple[int, str, Path]] = []
    seen_versions: dict[int, Path] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise StorageError(
                f"{path}: migration filenames must match NNNN_description.sql"
            )
        version = int(match.group(1))
        if version in seen_versions:
            raise StorageError(
                f"duplicate migration version {version}: "
                f"{seen_versions[version].name} and {path.name}"
            )
        seen_versions[version] = path
        found.append((version, path.stem, path))
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(_CREATE_TRACKING_TABLE)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def apply_migrations(
    conn: sqlite3.Connection, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
) -> list[int]:
    """Apply every migration not yet recorded, in version order.

    Returns the versions actually applied this call -- empty when the database
    was already current, which is what makes re-running this safe.
    """
    migrations = _discover(migrations_dir)
    already = applied_versions(conn)
    newly_applied: list[int] = []

    for version, name, path in migrations:
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        with conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (?, ?, datetime('now'))",
                (version, name),
            )
        newly_applied.append(version)

    return newly_applied

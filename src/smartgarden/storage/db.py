"""Opening a SmartGarden database (ARCH-5).

WAL mode plus an explicit busy_timeout is the whole trick: a long analytics
read (an export, a chart query) takes a snapshot instead of holding the
writer lock, so the control loop's next write never fails because someone had
a report open.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from smartgarden.storage.migrations import DEFAULT_MIGRATIONS_DIR, apply_migrations

__all__ = ["DEFAULT_BUSY_TIMEOUT_MS", "connect"]

DEFAULT_BUSY_TIMEOUT_MS = 5_000


def connect(
    path: str | Path,
    *,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    """Open (creating if needed) a database, migrated to the current schema.

    `path` may be `:memory:` for tests. WAL mode is skipped for an in-memory
    database -- SQLite does not support it there, and there is no second
    process to protect against.
    """
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")

    apply_migrations(conn, migrations_dir)
    return conn

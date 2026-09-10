"""Nightly backup and a tested restore path (STOR-4).

`VACUUM INTO` writes a compact, internally consistent snapshot in one step --
no need to stop the writer or copy the WAL/SHM files alongside the main one.
Restoring is the inverse: verify the snapshot opens clean, then replace the
live file with it.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from smartgarden.core.errors import StorageError

__all__ = ["backup_now", "restore_from_backup"]

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def backup_now(
    conn: sqlite3.Connection,
    backup_dir: Path,
    *,
    keep: int,
    at: datetime | None = None,
) -> Path:
    """Write a `VACUUM INTO` snapshot, then prune to the newest `keep`.

    `at` is injectable for tests; it defaults to the current UTC time. The
    filename embeds a UTC timestamp so backups sort chronologically by name,
    which is what makes "prune to the newest `keep`" a plain sort-and-slice.
    """
    if keep < 1:
        raise StorageError(f"backup_keep must be at least 1, got {keep}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (at or datetime.now(UTC)).strftime(_TIMESTAMP_FORMAT)
    dest = backup_dir / f"smartgarden-{stamp}.db"
    if dest.exists():
        raise StorageError(f"backup destination already exists: {dest}")

    conn.execute("VACUUM INTO ?", (str(dest),))

    existing = sorted(backup_dir.glob("smartgarden-*.db"))
    for stale in existing[:-keep]:
        stale.unlink()

    return dest


def restore_from_backup(backup_path: Path, dest_path: Path) -> None:
    """Replace `dest_path` with `backup_path`, after verifying it opens clean.

    This is the restore command STOR-4 requires be tested at least once --
    the storage tests back up a live database, delete it (WAL and SHM
    included), restore, and confirm the data reads back unchanged.
    """
    if not backup_path.is_file():
        raise StorageError(f"backup file does not exist: {backup_path}")

    check = sqlite3.connect(str(backup_path))
    try:
        row = check.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise StorageError(f"backup at {backup_path} failed integrity_check: {row}")
    finally:
        check.close()

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = Path(f"{dest_path}{suffix}")
        if stale.exists():
            stale.unlink()
    shutil.copyfile(backup_path, dest_path)

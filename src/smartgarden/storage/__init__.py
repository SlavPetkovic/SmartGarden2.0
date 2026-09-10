"""Persistence: migrations, repositories, rollups, backup and export.

Layer 2. Storage may import `core` -- it serialises the shapes core defines --
but nothing in `core` may import back (ARCH-4). Everything here does real I/O:
opening the database file, reading and writing rows, touching the filesystem
for backups and exports.

All timestamps entering or leaving this layer are UTC and timezone-aware
(STOR-6); `smartgarden.storage.timeutil` is where that is enforced.
"""

from __future__ import annotations

from smartgarden.storage.backup import backup_now, restore_from_backup
from smartgarden.storage.db import DEFAULT_BUSY_TIMEOUT_MS, connect
from smartgarden.storage.export import export_range
from smartgarden.storage.migrations import DEFAULT_MIGRATIONS_DIR, apply_migrations
from smartgarden.storage.repository import Repository
from smartgarden.storage.rollup import Tier, run_rollup

__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_MIGRATIONS_DIR",
    "Repository",
    "Tier",
    "apply_migrations",
    "backup_now",
    "connect",
    "export_range",
    "restore_from_backup",
    "run_rollup",
]

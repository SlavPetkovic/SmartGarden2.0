"""Backup and restore (STOR-4): VACUUM INTO, a retention count, and a restore
path this test actually exercises."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smartgarden.core.errors import StorageError
from smartgarden.core.models import ChannelSpec, Reading, Zone
from smartgarden.storage.backup import backup_now, restore_from_backup
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

NOW = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)


class TestBackupNow(unittest.TestCase):
    def test_writes_a_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "live.db")
            dest = backup_now(conn, Path(tmp) / "backups", keep=7, at=NOW)
            conn.close()  # WAL keeps the file open; Windows can't rmtree it otherwise
            self.assertTrue(dest.is_file())
            self.assertGreater(dest.stat().st_size, 0)

    def test_prunes_to_the_newest_keep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "live.db")
            backup_dir = Path(tmp) / "backups"
            for i in range(5):
                backup_now(conn, backup_dir, keep=3, at=NOW + timedelta(days=i))
            conn.close()
            remaining = sorted(backup_dir.glob("smartgarden-*.db"))
            # Filenames embed the timestamp, so "kept the newest three" is
            # exactly "kept the three whose day index is 2, 3, 4".
            expected = [
                (NOW + timedelta(days=i)).strftime("smartgarden-%Y%m%dT%H%M%SZ.db")
                for i in range(2, 5)
            ]
            self.assertEqual([p.name for p in remaining], expected)

    def test_rejects_keep_less_than_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "live.db")
            try:
                with self.assertRaises(StorageError):
                    backup_now(conn, Path(tmp) / "backups", keep=0, at=NOW)
            finally:
                conn.close()


class TestRestoreFromBackup(unittest.TestCase):
    def test_restores_data_after_the_live_database_is_lost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_path = Path(tmp) / "live.db"
            conn = connect(live_path)
            repo = Repository(conn)
            repo.upsert_node("pi-local", kind="local", stale_after_seconds=60.0)
            repo.upsert_zone(Zone(slug="windowsill", name="Windowsill"))
            repo.upsert_sensor(
                "soil-1", node="pi-local", driver="seesaw_soil", interval_seconds=60.0
            )
            channel_id = repo.reconcile_channels(
                "soil-1", [ChannelSpec(key="moisture", unit="counts")]
            )["moisture"]
            repo.insert_reading(Reading(channel_id=channel_id, at=NOW, value=555.0))

            backup_dir = Path(tmp) / "backups"
            backup_path = backup_now(conn, backup_dir, keep=7, at=NOW)
            conn.close()

            # Simulate total loss of the live database, WAL and SHM included.
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(f"{live_path}{suffix}")
                if candidate.exists():
                    candidate.unlink()
            self.assertFalse(live_path.exists())

            restore_from_backup(backup_path, live_path)

            restored = connect(live_path)
            row = restored.execute("SELECT value FROM reading").fetchone()
            self.assertEqual(row["value"], 555.0)
            restored.close()

    def test_missing_backup_file_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(StorageError):
            restore_from_backup(Path(tmp) / "does-not-exist.db", Path(tmp) / "live.db")


if __name__ == "__main__":
    unittest.main()

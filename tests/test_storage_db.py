"""Connecting to the database: WAL mode, busy_timeout, timezone-aware I/O
(ARCH-5, STOR-6)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from smartgarden.core.errors import StorageError
from smartgarden.storage.db import connect
from smartgarden.storage.timeutil import from_iso, to_iso


class TestConnect(unittest.TestCase):
    def test_file_database_opens_in_wal_mode_with_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smartgarden.db"
            conn = connect(path, busy_timeout_ms=2_500)
            try:
                (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
                self.assertEqual(mode.lower(), "wal")
                (timeout,) = conn.execute("PRAGMA busy_timeout").fetchone()
                self.assertEqual(timeout, 2_500)
            finally:
                conn.close()

    def test_memory_database_skips_wal_but_still_migrates(self) -> None:
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        self.assertIn("channel", tables)


class TestTimeutil(unittest.TestCase):
    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaises(StorageError):
            to_iso(datetime(2026, 9, 9, 12, 0))  # no tzinfo

    def test_round_trips_timezone_aware(self) -> None:
        at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        self.assertEqual(from_iso(to_iso(at)), at)

    def test_naive_stored_text_is_rejected_on_read(self) -> None:
        with self.assertRaises(StorageError):
            from_iso("2026-09-09T12:00:00")


if __name__ == "__main__":
    unittest.main()

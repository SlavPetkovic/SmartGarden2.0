"""Connecting to the database: WAL mode, busy_timeout, timezone-aware I/O
(ARCH-5, STOR-6)."""

from __future__ import annotations

import concurrent.futures
import sqlite3
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


class TestCheckSameThread(unittest.TestCase):
    """web/deps.py:get_repo opens a connection on one of FastAPI's threadpool
    worker threads and closes it on another -- a real bug (found live, on
    the Pi, in every single request) that a `TestClient` call never
    reproduces, because nothing there forces open and close onto genuinely
    different OS threads the way anyio's threadpool does under FastAPI's
    sync-dependency-generator handling. These use two single-worker
    executors specifically so open and close are *guaranteed* to happen on
    different threads, rather than hoping a shared pool schedules that way.
    """

    def test_default_rejects_close_from_a_different_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smartgarden.db"
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as opener,
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as closer,
            ):
                conn = opener.submit(connect, path).result()
                with self.assertRaises(sqlite3.ProgrammingError):
                    closer.submit(conn.close).result()
                # Clean up from the thread that actually owns it.
                opener.submit(conn.close).result()

    def test_check_same_thread_false_allows_close_from_a_different_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "smartgarden.db"
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as opener,
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as closer,
            ):
                conn = opener.submit(connect, path, check_same_thread=False).result()
                closer.submit(conn.close).result()  # must not raise


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

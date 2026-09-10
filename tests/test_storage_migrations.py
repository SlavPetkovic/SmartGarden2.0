"""Migrations: numbered, ordered, and safe to re-apply (STOR-1, DATA-1)."""

from __future__ import annotations

import sqlite3
import unittest

from smartgarden.storage.migrations import applied_versions, apply_migrations


class TestApplyMigrations(unittest.TestCase):
    def test_applies_at_least_one_migration_to_a_fresh_database(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        applied = apply_migrations(conn)
        self.assertGreater(len(applied), 0)
        self.assertEqual(applied_versions(conn), set(applied))

    def test_reapplying_is_a_no_op(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        first = apply_migrations(conn)
        before_tables = _table_names(conn)

        second = apply_migrations(conn)

        self.assertEqual(second, [])
        self.assertEqual(_table_names(conn), before_tables)
        # Every version recorded exactly once.
        rows = conn.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version"
        ).fetchall()
        for _version, count in rows:
            self.assertEqual(count, 1)
        self.assertTrue(set(first))

    def test_expected_tables_exist(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        apply_migrations(conn)
        tables = _table_names(conn)
        for expected in (
            "schema_migrations",
            "node",
            "zone",
            "plant",
            "device",
            "sensor",
            "channel",
            "reading",
            "reading_rollup",
            "decision",
            "command",
            "actuation",
        ):
            self.assertIn(expected, tables)


class TestReadingIsNarrow(unittest.TestCase):
    """DATA-1: one row per (channel, timestamp, value). No column per measurement."""

    def test_reading_columns_do_not_name_a_measurement(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        apply_migrations(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reading)")}
        self.assertEqual(columns, {"id", "channel_id", "ts", "value", "quality"})


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


if __name__ == "__main__":
    unittest.main()

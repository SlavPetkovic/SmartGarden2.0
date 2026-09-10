"""VPD gets its own channel per zone, reconciled idempotently (CTRL-10, ML-1)."""

from __future__ import annotations

import unittest

from smartgarden.core.models import ChannelRole, Zone
from smartgarden.runtime.derived import (
    DERIVED_NODE_SLUG,
    derived_sensor_slug,
    ensure_derived_channels,
)
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository


class TestEnsureDerivedChannels(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)
        self.repo.upsert_zone(Zone(slug="windowsill", name="Windowsill"))

    def test_creates_a_vpd_channel_bound_to_the_zone(self) -> None:
        result = ensure_derived_channels(self.repo, ["windowsill"])
        vpd_channel_id = result["windowsill"]

        row = self.conn.execute(
            "SELECT role, zone_id FROM channel WHERE id = ?", (vpd_channel_id,)
        ).fetchone()
        self.assertEqual(row["role"], ChannelRole.VPD.value)

        zone_row = self.conn.execute(
            "SELECT id FROM zone WHERE slug = 'windowsill'"
        ).fetchone()
        self.assertEqual(row["zone_id"], zone_row["id"])

    def test_idempotent(self) -> None:
        first = ensure_derived_channels(self.repo, ["windowsill"])
        second = ensure_derived_channels(self.repo, ["windowsill"])
        self.assertEqual(first, second)

    def test_no_zones_creates_nothing(self) -> None:
        self.assertEqual(ensure_derived_channels(self.repo, []), {})
        tables = self.conn.execute(
            "SELECT COUNT(*) FROM node WHERE slug = ?", (DERIVED_NODE_SLUG,)
        ).fetchone()
        self.assertEqual(tables[0], 0)

    def test_sensor_slug_is_namespaced_per_zone(self) -> None:
        self.assertEqual(derived_sensor_slug("windowsill"), "derived-windowsill")


if __name__ == "__main__":
    unittest.main()

"""The JSON API: channel metadata (API-2), time-series tier selection over
HTTP (API-3), ingest (ARCH-6), commands (ARCH-3), and token auth (API-4).

Needs the [web] extra (fastapi, uvicorn, pydantic) to import at all, so
every test class here self-skips under tests-bare the same way
tests/test_cli.py's doctor test self-skips without I2C hardware libraries:
an explicit unittest skip, not a pytest marker, since tests-bare runs via
`unittest discover`, not pytest.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smartgarden.config.schema import (
    AppConfig,
    Config,
    NodeConfig,
    PlantConfig,
    SensorConfig,
    ZoneConfig,
)
from smartgarden.runtime.wiring import build_control_loop
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository
from smartgarden.storage.rollup import Tier, run_rollup

try:
    from fastapi.testclient import TestClient

    from smartgarden.web import create_app

    _HAS_WEB = True
except ImportError:
    _HAS_WEB = False

START = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _config(*, api_token: str | None = None) -> Config:
    return Config(
        app=AppConfig(api_token=api_token),
        nodes=(NodeConfig(slug="pi-local", stale_after_seconds=60.0),),
        zones=(ZoneConfig(slug="windowsill", name="Windowsill"),),
        plants=(PlantConfig(slug="monstera", name="Monstera", zone="windowsill"),),
        sensors=(
            SensorConfig(
                slug="air-1",
                node="pi-local",
                driver="simulated_bme680",
                zone="windowsill",
                interval_seconds=10.0,
            ),
            SensorConfig(
                slug="soil-1",
                node="pi-local",
                driver="simulated_seesaw_soil",
                zone="windowsill",
                plant="monstera",
                interval_seconds=60.0,
            ),
        ),
    )


def _seed_app(*, api_token: str | None = None) -> tuple[TestClient, str]:
    """A real db seeded by one tick of the actual control loop, plus a
    rollup pass -- the API is tested against the same pipeline layer 04a
    produces, not a hand-built fixture."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "smartgarden.db"
    config = _config(api_token=api_token)

    conn = connect(db_path)
    loop = build_control_loop(Repository(conn), config)
    loop.clock = lambda: 0.0
    loop.now = lambda: START
    loop.tick()
    window = (START - timedelta(minutes=1), START + timedelta(minutes=1))
    run_rollup(conn, Tier.MINUTE, *window)
    run_rollup(conn, Tier.QUARTER_HOUR, *window)
    conn.close()

    return TestClient(create_app(config, db_path)), tmp_dir


# gate: allow-skip -- exercises the [web] extra (fastapi/uvicorn/pydantic),
# not installed under tests-bare; see docs/git-workflow.md section 4.
@unittest.skipUnless(_HAS_WEB, "requires the [web] extra")
class TestChannelsEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._tmp = _seed_app()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_lists_channels_with_role_zone_and_plant(self) -> None:
        resp = self.client.get("/channels")
        self.assertEqual(resp.status_code, 200)
        moisture = next(c for c in resp.json() if c["key"] == "moisture")
        self.assertEqual(moisture["role"], "soil_moisture")
        self.assertEqual(moisture["zone"], "windowsill")
        self.assertEqual(moisture["plant"], "monstera")


# gate: allow-skip -- exercises the [web] extra (fastapi/uvicorn/pydantic),
# not installed under tests-bare; see docs/git-workflow.md section 4.
@unittest.skipUnless(_HAS_WEB, "requires the [web] extra")
class TestTimeseriesEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._tmp = _seed_app()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        channels = {c["key"]: c["id"] for c in self.client.get("/channels").json()}
        self.moisture_id = channels["moisture"]

    def test_one_hour_range_returns_raw_points(self) -> None:
        resp = self.client.get(
            f"/channels/{self.moisture_id}/timeseries",
            params={
                "start": (START - timedelta(minutes=30)).isoformat(),
                "end": (START + timedelta(minutes=30)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["tier"], "raw")
        self.assertEqual(len(body["raw"]), 1)
        self.assertEqual(body["rollup"], [])

    def test_sixty_day_range_returns_quarter_hour_rollup(self) -> None:
        resp = self.client.get(
            f"/channels/{self.moisture_id}/timeseries",
            params={
                "start": (START - timedelta(days=60)).isoformat(),
                "end": (START + timedelta(minutes=1)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["tier"], "quarter_hour")
        self.assertEqual(len(body["rollup"]), 1)
        self.assertEqual(body["raw"], [])

    def test_naive_datetimes_are_rejected(self) -> None:
        resp = self.client.get(
            f"/channels/{self.moisture_id}/timeseries",
            params={"start": "2026-09-10T00:00:00", "end": "2026-09-10T01:00:00"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_end_before_start_is_rejected(self) -> None:
        resp = self.client.get(
            f"/channels/{self.moisture_id}/timeseries",
            params={
                "start": START.isoformat(),
                "end": (START - timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 422)


# gate: allow-skip -- exercises the [web] extra (fastapi/uvicorn/pydantic),
# not installed under tests-bare; see docs/git-workflow.md section 4.
@unittest.skipUnless(_HAS_WEB, "requires the [web] extra")
class TestIngestReachesTheSamePlaceALocalReadingDoes(unittest.TestCase):
    """ARCH-6, verbatim from BUILD-PLAN.md's layer 05 gate: "a test posts a
    reading under a second node id and asserts it lands in the same tables,
    resolves the same roles and reaches the same time-series endpoints as
    one from the local bus." """

    def setUp(self) -> None:
        self.client, self._tmp = _seed_app()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_ingested_reading_is_indistinguishable_downstream(self) -> None:
        payload = {
            "node": "bed-1",
            "node_kind": "remote",
            "sensor": "soil-bed1",
            "driver": "seesaw_soil",
            "zone": "windowsill",
            "at": START.isoformat(),
            "channels": [
                {
                    "key": "moisture",
                    "unit": "counts",
                    "role": "soil_moisture",
                    "plausible_min": 180.0,
                    "plausible_max": 2100.0,
                }
            ],
            "readings": [{"key": "moisture", "value": 777.0}],
        }
        ingest_resp = self.client.post("/ingest", json=payload)
        self.assertEqual(ingest_resp.status_code, 201, ingest_resp.text)
        self.assertEqual(ingest_resp.json()["accepted"], 1)

        channels = self.client.get("/channels").json()
        remote_channel = next(c for c in channels if c["sensor"] == "soil-bed1")
        # Same role resolution as the local bus's own moisture channel.
        self.assertEqual(remote_channel["role"], "soil_moisture")
        self.assertEqual(remote_channel["zone"], "windowsill")

        ts_resp = self.client.get(
            f"/channels/{remote_channel['id']}/timeseries",
            params={
                "start": (START - timedelta(minutes=1)).isoformat(),
                "end": (START + timedelta(minutes=1)).isoformat(),
            },
        )
        self.assertEqual(ts_resp.status_code, 200)
        body = ts_resp.json()
        self.assertEqual(body["tier"], "raw")
        self.assertEqual(len(body["raw"]), 1)
        self.assertEqual(body["raw"][0]["value"], 777.0)

    def test_unknown_zone_is_a_client_error_not_a_crash(self) -> None:
        payload = {
            "node": "bed-1",
            "sensor": "soil-bed1",
            "driver": "seesaw_soil",
            "zone": "no-such-zone",
            "at": START.isoformat(),
            "channels": [{"key": "moisture", "unit": "counts"}],
            "readings": [{"key": "moisture", "value": 500.0}],
        }
        resp = self.client.post("/ingest", json=payload)
        self.assertEqual(resp.status_code, 404)


# gate: allow-skip -- exercises the [web] extra (fastapi/uvicorn/pydantic),
# not installed under tests-bare; see docs/git-workflow.md section 4.
@unittest.skipUnless(_HAS_WEB, "requires the [web] extra")
class TestCommandsEndpoint(unittest.TestCase):
    """A manual action becomes a `commands` row, not a driven output
    (ARCH-3) -- this process cannot reach a device either way."""

    def setUp(self) -> None:
        self.client, self._tmp = _seed_app()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def test_creates_and_lists_a_pending_command(self) -> None:
        create_resp = self.client.post(
            "/zones/windowsill/commands", json={"kind": "water_now"}
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)
        body = create_resp.json()
        self.assertTrue(body["pending"])
        self.assertEqual(body["zone"], "windowsill")

        pending = self.client.get("/commands").json()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], "water_now")

    def test_unknown_command_kind_is_rejected(self) -> None:
        resp = self.client.post(
            "/zones/windowsill/commands", json={"kind": "not-a-real-kind"}
        )
        self.assertEqual(resp.status_code, 422)

    def test_unknown_zone_is_a_404(self) -> None:
        resp = self.client.post(
            "/zones/does-not-exist/commands", json={"kind": "water_now"}
        )
        self.assertEqual(resp.status_code, 404)


# gate: allow-skip -- exercises the [web] extra (fastapi/uvicorn/pydantic),
# not installed under tests-bare; see docs/git-workflow.md section 4.
@unittest.skipUnless(_HAS_WEB, "requires the [web] extra")
class TestTokenAuth(unittest.TestCase):
    """API-4: implemented, disabled by default, enabled by one config value."""

    def test_disabled_by_default(self) -> None:
        client, tmp = _seed_app()
        try:
            self.assertEqual(client.get("/channels").status_code, 200)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enabled_by_setting_api_token(self) -> None:
        client, tmp = _seed_app(api_token="secret123")
        try:
            self.assertEqual(client.get("/channels").status_code, 401)
            self.assertEqual(
                client.get(
                    "/channels", headers={"Authorization": "Bearer secret123"}
                ).status_code,
                200,
            )
            self.assertEqual(
                client.get(
                    "/channels", headers={"Authorization": "Bearer wrong"}
                ).status_code,
                401,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

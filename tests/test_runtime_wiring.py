"""Config -> a running loop: driver dispatch and role overrides (SENS-1,
DATA-2, DATA-3)."""

from __future__ import annotations

import unittest

from smartgarden.config.schema import (
    AppConfig,
    Config,
    NodeConfig,
    SensorConfig,
    ZoneConfig,
)
from smartgarden.core.errors import ConfigError
from smartgarden.core.models import ChannelRole
from smartgarden.drivers.sensors.simulated import SimulatedSoilSensor
from smartgarden.runtime.wiring import build_control_loop, build_driver
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository


def _config(sensors: tuple[SensorConfig, ...] | None = None) -> Config:
    return Config(
        app=AppConfig(),
        nodes=(NodeConfig(slug="pi-local", stale_after_seconds=60.0),),
        zones=(ZoneConfig(slug="windowsill", name="Windowsill"),),
        sensors=sensors
        or (
            SensorConfig(
                slug="soil-1",
                node="pi-local",
                driver="simulated_seesaw_soil",
                interval_seconds=60.0,
                zone="windowsill",
            ),
        ),
    )


class TestBuildDriver(unittest.TestCase):
    def test_simulated_driver_needs_no_address(self) -> None:
        sensor = SensorConfig(
            slug="soil-1", node="pi-local", driver="simulated_seesaw_soil"
        )
        self.assertIsInstance(build_driver(sensor), SimulatedSoilSensor)

    def test_real_driver_without_an_address_is_a_config_error(self) -> None:
        sensor = SensorConfig(slug="soil-1", node="pi-local", driver="seesaw_soil")
        with self.assertRaises(ConfigError):
            build_driver(sensor)


class TestBuildControlLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.repo = Repository(self.conn)

    def test_reconciles_channels_for_every_enabled_sensor(self) -> None:
        loop = build_control_loop(self.repo, _config())
        self.assertEqual(len(loop.bindings), 1)
        self.assertIn("moisture", loop.bindings[0].channel_ids)

    def test_disabled_sensor_is_not_bound(self) -> None:
        config = _config(
            sensors=(
                SensorConfig(
                    slug="soil-1",
                    node="pi-local",
                    driver="simulated_seesaw_soil",
                    zone="windowsill",
                    enabled=False,
                ),
            )
        )
        loop = build_control_loop(self.repo, config)
        self.assertEqual(loop.bindings, [])

    def test_role_override_applies_only_to_the_named_key(self) -> None:
        # simulated_seesaw_soil's own defaults are moisture->SOIL_MOISTURE,
        # temperature->SOIL_TEMP. Override only "moisture", to something
        # deliberately unrelated so a coincidental match can't hide a bug.
        config = _config(
            sensors=(
                SensorConfig(
                    slug="soil-1",
                    node="pi-local",
                    driver="simulated_seesaw_soil",
                    zone="windowsill",
                    roles={"moisture": ChannelRole.LIGHT},
                ),
            )
        )
        build_control_loop(self.repo, config)
        moisture = self.conn.execute(
            "SELECT role FROM channel WHERE key = 'moisture'"
        ).fetchone()
        temperature = self.conn.execute(
            "SELECT role FROM channel WHERE key = 'temperature'"
        ).fetchone()
        self.assertEqual(moisture["role"], ChannelRole.LIGHT.value)  # overridden
        self.assertEqual(temperature["role"], ChannelRole.SOIL_TEMP.value)  # untouched

    def test_creates_a_vpd_channel_per_zone(self) -> None:
        loop = build_control_loop(self.repo, _config())
        self.assertIn("windowsill", loop.vpd_channel_ids)


if __name__ == "__main__":
    unittest.main()

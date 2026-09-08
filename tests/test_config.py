"""Tests for configuration loading and validation.

The valuable cases here are the cross-file ones: a sensor pointing at a node
that does not exist, two devices sharing a pin, two sensors at the same bus
address. Those are the mistakes that are easy to make and silent at runtime.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smartgarden.config import load_config
from smartgarden.core.errors import ConfigError

APP = """
[app]
database_path = "data/test.db"
"""

SENSORS = """
[[node]]
slug = "pi-local"

[[sensor]]
slug = "soil-1"
node = "pi-local"
driver = "seesaw_soil"
address = 0x36
zone = "windowsill"
[sensor.roles]
moisture = "soil_moisture"
"""

DEVICES = """
[[zone]]
slug = "windowsill"
name = "Windowsill"

[[device]]
slug = "pump-1"
kind = "irrigate"
zone = "windowsill"
driver = "gpio_relay"
pin = 23
max_on_seconds = 10.0
pulse_seconds = 6.0
"""

PLANTS = """
[[plant]]
slug = "monstera"
name = "Monstera"
zone = "windowsill"
moisture_low = 450.0
moisture_high = 800.0
"""


class _ConfigCase(unittest.TestCase):
    """Base that writes a four-file config into a temp directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, **overrides: str) -> Path:
        files = {
            "app.toml": APP,
            "sensors.toml": SENSORS,
            "devices.toml": DEVICES,
            "plants.toml": PLANTS,
        }
        files.update(overrides)
        for name, content in files.items():
            (self.dir / name).write_text(content)
        return self.dir


class TestHappyPath(_ConfigCase):
    def test_loads_valid_configuration(self) -> None:
        config = load_config(self.write())
        self.assertEqual(len(config.nodes), 1)
        self.assertEqual(len(config.sensors), 1)
        self.assertEqual(len(config.zones), 1)
        self.assertEqual(len(config.devices), 1)
        self.assertEqual(len(config.plants), 1)

    def test_automation_defaults_off(self) -> None:
        """Shipping with automation on would water against uncalibrated thresholds."""
        self.assertFalse(load_config(self.write()).app.automation_enabled)

    def test_optional_files_may_be_absent(self) -> None:
        (self.dir / "app.toml").write_text(APP)
        config = load_config(self.dir)
        self.assertEqual(config.sensors, ())
        self.assertEqual(config.zones, ())

    def test_lookups(self) -> None:
        config = load_config(self.write())
        self.assertEqual(config.zone("windowsill").name, "Windowsill")
        self.assertEqual(len(config.plants_in("windowsill")), 1)
        self.assertEqual(len(config.devices_in("windowsill")), 1)
        self.assertEqual(len(config.sensors_on("pi-local")), 1)
        with self.assertRaises(KeyError):
            config.zone("nope")

    def test_roles_parse_into_enum(self) -> None:
        config = load_config(self.write())
        self.assertEqual(config.sensors[0].roles["moisture"].value, "soil_moisture")

    def test_integer_literals_accepted_for_float_fields(self) -> None:
        """TOML has no float suffix; people write `120`, not `120.0`."""
        app = APP + "\ntick_seconds = 30\n"
        config = load_config(self.write(**{"app.toml": app}))
        self.assertEqual(config.app.tick_seconds, 30.0)


class TestFileLevelFailures(_ConfigCase):
    def test_missing_directory(self) -> None:
        with self.assertRaisesRegex(ConfigError, "does not exist"):
            load_config(self.dir / "absent")

    def test_missing_app_file(self) -> None:
        with self.assertRaisesRegex(ConfigError, "app.toml.*missing"):
            load_config(self.dir)

    def test_malformed_toml_names_the_file(self) -> None:
        (self.dir / "app.toml").write_text("[app\nbroken")
        with self.assertRaisesRegex(ConfigError, "invalid TOML"):
            load_config(self.dir)

    def test_unknown_key_is_rejected(self) -> None:
        """A typo'd key that silently does nothing is how a safety limit stops
        applying without anyone noticing."""
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            load_config(self.write(**{"app.toml": APP + "\ntypoed_key = 1\n"}))

    def test_wrong_type_names_the_key(self) -> None:
        bad = APP + '\nbackup_keep = "seven"\n'
        with self.assertRaisesRegex(ConfigError, "backup_keep.*whole number"):
            load_config(self.write(**{"app.toml": bad}))

    def test_missing_required_key(self) -> None:
        bad = DEVICES.replace('name = "Windowsill"', "")
        with self.assertRaisesRegex(ConfigError, "required key 'name'"):
            load_config(self.write(**{"devices.toml": bad}))

    def test_unknown_role_lists_the_valid_ones(self) -> None:
        bad = SENSORS.replace("moisture = \"soil_moisture\"", "moisture = \"wetness\"")
        with self.assertRaisesRegex(ConfigError, "Known roles"):
            load_config(self.write(**{"sensors.toml": bad}))


class TestCrossReferences(_ConfigCase):
    def test_sensor_on_unknown_node(self) -> None:
        bad = SENSORS.replace('node = "pi-local"\ndriver', 'node = "ghost"\ndriver')
        with self.assertRaisesRegex(ConfigError, "unknown node 'ghost'"):
            load_config(self.write(**{"sensors.toml": bad}))

    def test_device_in_unknown_zone(self) -> None:
        bad = DEVICES.replace('zone = "windowsill"\ndriver', 'zone = "greenhouse"\ndriver')
        with self.assertRaisesRegex(ConfigError, "unknown zone 'greenhouse'"):
            load_config(self.write(**{"devices.toml": bad}))

    def test_plant_in_unknown_zone(self) -> None:
        bad = PLANTS.replace('zone = "windowsill"', 'zone = "balcony"')
        with self.assertRaisesRegex(ConfigError, "unknown zone 'balcony'"):
            load_config(self.write(**{"plants.toml": bad}))

    def test_duplicate_slugs_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "duplicate plant slug"):
            load_config(self.write(**{"plants.toml": PLANTS + PLANTS}))


class TestHardwareConflicts(_ConfigCase):
    LIGHT_ON_23 = """
[[device]]
slug = "light-1"
kind = "light"
zone = "windowsill"
driver = "gpio_relay"
pin = 23
fixture_ppfd = 120.0
"""

    def test_two_real_devices_cannot_share_a_pin(self) -> None:
        with self.assertRaisesRegex(ConfigError, "BCM pin 23"):
            load_config(self.write(**{"devices.toml": DEVICES + self.LIGHT_ON_23}))

    def test_simulated_devices_may_share_a_pin(self) -> None:
        """Simulated drivers touch no hardware, so overlap is harmless -- and
        forbidding it would make the no-hardware config tedious to write."""
        both = DEVICES.replace('driver = "gpio_relay"', 'driver = "simulated"') + (
            self.LIGHT_ON_23.replace('driver = "gpio_relay"', 'driver = "simulated"')
        )
        self.assertEqual(len(load_config(self.write(**{"devices.toml": both})).devices), 2)

    def test_two_sensors_cannot_share_a_bus_address(self) -> None:
        clash = SENSORS + """
[[sensor]]
slug = "soil-2"
node = "pi-local"
driver = "seesaw_soil"
address = 0x36
zone = "windowsill"
"""
        with self.assertRaisesRegex(ConfigError, "share address 0x36"):
            load_config(self.write(**{"sensors.toml": clash}))

    def test_same_address_on_different_mux_channels_is_fine(self) -> None:
        """This is exactly what a multiplexer is for."""
        muxed = SENSORS + """
[[sensor]]
slug = "soil-2"
node = "pi-local"
driver = "seesaw_soil"
address = 0x36
mux_address = 0x70
mux_channel = 1
zone = "windowsill"
"""
        self.assertEqual(len(load_config(self.write(**{"sensors.toml": muxed})).sensors), 2)

    def test_half_specified_mux_is_rejected(self) -> None:
        bad = SENSORS + """
[[sensor]]
slug = "soil-2"
node = "pi-local"
driver = "seesaw_soil"
address = 0x37
mux_channel = 1
zone = "windowsill"
"""
        with self.assertRaisesRegex(ConfigError, "both mux_address and mux_channel"):
            load_config(self.write(**{"sensors.toml": bad}))


class TestSafetyInvariants(_ConfigCase):
    def test_pulse_cannot_exceed_device_hard_limit(self) -> None:
        bad = DEVICES.replace("pulse_seconds = 6.0", "pulse_seconds = 25.0")
        with self.assertRaisesRegex(ConfigError, "exceeds max_on_seconds"):
            load_config(self.write(**{"devices.toml": bad}))

    def test_light_requires_fixture_ppfd(self) -> None:
        """Without it there is no way to convert a DLI shortfall into runtime."""
        bad = DEVICES + """
[[device]]
slug = "light-1"
kind = "light"
zone = "windowsill"
pin = 24
"""
        with self.assertRaisesRegex(ConfigError, "fixture_ppfd"):
            load_config(self.write(**{"devices.toml": bad}))

    def test_retention_tiers_must_be_ordered(self) -> None:
        bad = APP + "\nraw_retention_days = 30\nminute_retention_days = 7\n"
        with self.assertRaisesRegex(ConfigError, "at least raw_retention_days"):
            load_config(self.write(**{"app.toml": bad}))

    def test_inverted_moisture_band_rejected(self) -> None:
        bad = PLANTS.replace("moisture_low = 450.0", "moisture_low = 900.0")
        with self.assertRaisesRegex(ConfigError, "must be below"):
            load_config(self.write(**{"plants.toml": bad}))

    def test_negative_budget_rejected(self) -> None:
        bad = DEVICES.replace(
            'name = "Windowsill"', 'name = "Windowsill"\ndaily_budget_seconds = -5.0'
        )
        with self.assertRaisesRegex(ConfigError, "at least 0"):
            load_config(self.write(**{"devices.toml": bad}))


class TestRealShippedConfig(unittest.TestCase):
    def test_repository_config_is_valid(self) -> None:
        """The config committed to the repo must actually load."""
        repo_config = Path(__file__).resolve().parents[1] / "config"
        config = load_config(repo_config)
        self.assertTrue(config.zones, "shipped config should define a zone")
        self.assertFalse(config.app.automation_enabled)

    def test_shipped_config_converts_to_core_types(self) -> None:
        repo_config = Path(__file__).resolve().parents[1] / "config"
        config = load_config(repo_config)
        for zone in config.zones:
            zone.to_core()
        for device in config.devices:
            device.to_core()
        for plant in config.plants:
            plant.to_core()


if __name__ == "__main__":
    unittest.main()

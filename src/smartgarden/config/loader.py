"""Loading configuration from TOML.

Four files, each with an obvious job:

    app.toml      runtime settings -- paths, intervals, retention
    sensors.toml  nodes and the sensors attached to them
    devices.toml  zones and the outputs that serve them
    plants.toml   plants and their seed care profiles

Missing optional files are fine and yield empty collections; a malformed file is
always fatal. Every failure raises ConfigError with the file named, so callers
catch one thing and exit cleanly, and the reader knows which file to open.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from smartgarden.config.schema import (
    AppConfig,
    Config,
    DeviceConfig,
    NodeConfig,
    PlantConfig,
    SensorConfig,
    ZoneConfig,
    _parse_list,
)
from smartgarden.core.errors import ConfigError

__all__ = ["DEFAULT_CONFIG_DIR", "load_config"]

DEFAULT_CONFIG_DIR = Path("config")

APP_FILE = "app.toml"
SENSORS_FILE = "sensors.toml"
DEVICES_FILE = "devices.toml"
PLANTS_FILE = "plants.toml"


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Config:
    """Read, merge and validate the configuration directory."""
    directory = Path(config_dir)
    if not directory.is_dir():
        raise ConfigError(
            f"configuration directory '{directory}' does not exist. "
            "Copy config/ from the repository, or pass --config-dir."
        )

    app_path = directory / APP_FILE
    if not app_path.is_file():
        raise ConfigError(
            f"required file '{app_path}' is missing. Every other config file is "
            "optional, but this one carries the database path and retention settings."
        )

    app_doc = _read_toml(app_path)
    sensors_doc = _read_toml_optional(directory / SENSORS_FILE)
    devices_doc = _read_toml_optional(directory / DEVICES_FILE)
    plants_doc = _read_toml_optional(directory / PLANTS_FILE)

    # A bare app.toml without the [app] header is accepted, since that is the
    # shape people write first and the intent is unambiguous.
    app_table = app_doc.get("app", app_doc)

    return Config(
        app=AppConfig.parse(app_table),
        nodes=_parse_list(sensors_doc.get("node"), NodeConfig.parse, "node"),
        sensors=_parse_list(sensors_doc.get("sensor"), SensorConfig.parse, "sensor"),
        zones=_parse_list(devices_doc.get("zone"), ZoneConfig.parse, "zone"),
        devices=_parse_list(devices_doc.get("device"), DeviceConfig.parse, "device"),
        plants=_parse_list(plants_doc.get("plant"), PlantConfig.parse, "plant"),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML -- {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot be read -- {exc}") from exc


def _read_toml_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _read_toml(path)

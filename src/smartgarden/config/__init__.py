"""Configuration loading and validation."""

from smartgarden.config.loader import DEFAULT_CONFIG_DIR, load_config
from smartgarden.config.schema import (
    AppConfig,
    Config,
    DeviceConfig,
    NodeConfig,
    PlantConfig,
    SensorConfig,
    ZoneConfig,
)

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "AppConfig",
    "Config",
    "DeviceConfig",
    "NodeConfig",
    "PlantConfig",
    "SensorConfig",
    "ZoneConfig",
    "load_config",
]

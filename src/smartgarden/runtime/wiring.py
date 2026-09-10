"""Turning validated config into a running `ControlLoop` (SENS-1, DATA-2).

The only place a config sensor's `driver` name turns into a constructed
driver instance. Real per-chip hardware construction stays delegated to
each driver module's own `create()`; this module does not re-implement it,
only dispatches to it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from smartgarden.config.schema import Config, SensorConfig
from smartgarden.core.errors import ConfigError
from smartgarden.core.models import ChannelRole, ChannelSpec
from smartgarden.drivers.base import SensorDriver
from smartgarden.drivers.i2c import I2CLocation
from smartgarden.drivers.registry import sensor_driver
from smartgarden.drivers.sensors import bme680, seesaw_soil, veml7700
from smartgarden.runtime.derived import ensure_derived_channels
from smartgarden.runtime.loop import ControlLoop, SensorBinding
from smartgarden.storage.repository import Repository

__all__ = ["build_control_loop", "build_driver"]

# Real chips need bus wiring (address, mux) their driver classes don't take
# directly (drivers/*.py's DI design -- see that module's docstring). This is
# the one place that maps a driver name to the factory that does it; every
# other driver name is resolved through the registry alone.
_HARDWARE_FACTORIES: dict[str, Callable[..., SensorDriver]] = {
    "bme680": bme680.create,
    "veml7700": veml7700.create,
    "seesaw_soil": seesaw_soil.create,
}


def build_driver(sensor: SensorConfig) -> SensorDriver:
    factory = _HARDWARE_FACTORIES.get(sensor.driver)
    if factory is not None:
        if sensor.address is None:
            raise ConfigError(
                f"sensor '{sensor.slug}' uses driver '{sensor.driver}', which needs "
                "an I2C address, but none is configured"
            )
        location = I2CLocation(sensor.address, sensor.mux_address, sensor.mux_channel)
        return factory(location, address=sensor.address)
    return sensor_driver(sensor.driver)()


def _with_role_overrides(
    specs: tuple[ChannelSpec, ...], roles: dict[str, ChannelRole]
) -> tuple[ChannelSpec, ...]:
    """Config's `[sensor.roles]` wins over a driver's own default (DATA-3):
    it is how one driver type serves channels with no built-in meaning, or
    a project chooses to bind a channel differently than the driver author
    assumed."""
    if not roles:
        return specs
    return tuple(
        replace(spec, role=roles[spec.key]) if spec.key in roles else spec
        for spec in specs
    )


def build_control_loop(repo: Repository, config: Config) -> ControlLoop:
    for node in config.nodes:
        repo.upsert_node(
            node.slug,
            kind=node.kind,
            description=node.description,
            stale_after_seconds=node.stale_after_seconds,
        )
    for zone in config.zones:
        repo.upsert_zone(zone.to_core())
    for plant in config.plants:
        repo.upsert_plant(plant.to_core())

    bindings = []
    for sensor in config.sensors:
        if not sensor.enabled:
            continue
        driver = build_driver(sensor)
        specs = _with_role_overrides(tuple(driver.channels()), sensor.roles)
        repo.upsert_sensor(
            sensor.slug,
            node=sensor.node,
            driver=sensor.driver,
            address=sensor.address,
            mux_address=sensor.mux_address,
            mux_channel=sensor.mux_channel,
            interval_seconds=sensor.interval_seconds,
            enabled=sensor.enabled,
        )
        channel_ids = repo.reconcile_channels(
            sensor.slug, specs, zone=sensor.zone, plant=sensor.plant
        )
        bindings.append(
            SensorBinding(
                slug=sensor.slug,
                driver=driver,
                interval_seconds=sensor.interval_seconds,
                node=sensor.node,
                zone=sensor.zone,
                channel_ids=channel_ids,
            )
        )

    vpd_channel_ids = ensure_derived_channels(repo, [zone.slug for zone in config.zones])

    return ControlLoop(
        repo=repo, config=config, bindings=bindings, vpd_channel_ids=vpd_channel_ids
    )

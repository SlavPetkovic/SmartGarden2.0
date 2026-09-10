"""Layer 04a -- the observe-only control loop (CTRL-8, CTRL-10, DATA-4, ML-1).

Reads every sensor at its own interval, stores what it reads, recomputes VPD
per zone every tick from the latest raw readings (never from a rollup), and
writes one decision row per zone every tick explaining what it observed.

This module holds no actuator, no `DeviceSpec`, and no import from
`smartgarden.drivers.actuators` -- there is nothing here that could drive a
device even if it tried. `tests/test_runtime_loop.py` proves that
architecturally: it wires in an actuator that raises if touched and runs a
full tick.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from smartgarden.config.schema import Config
from smartgarden.core.models import (
    ChannelRole,
    Decision,
    DecisionKind,
    NodeHealth,
    Quality,
    Reading,
)
from smartgarden.core.physics import vapour_pressure_deficit
from smartgarden.drivers.base import SensorDriver
from smartgarden.drivers.polling import poll_all
from smartgarden.storage.repository import Repository

__all__ = ["ControlLoop", "SensorBinding"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SensorBinding:
    """A configured sensor wired to a live driver, ready for the loop to poll."""

    slug: str
    driver: SensorDriver
    interval_seconds: float
    node: str
    channel_ids: Mapping[str, int]
    zone: str | None = None


@dataclass(slots=True)
class ControlLoop:
    repo: Repository
    config: Config
    bindings: list[SensorBinding]
    vpd_channel_ids: dict[str, int] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _last_polled: dict[str, float] = field(default_factory=dict, init=False)

    def tick(self) -> None:
        now_monotonic = self.clock()
        due = [
            binding
            for binding in self.bindings
            if now_monotonic - self._last_polled.get(binding.slug, float("-inf"))
            >= binding.interval_seconds
        ]

        at = self._poll_due(due, now_monotonic) if due else self.now()

        self._update_derived_vpd(at)
        self._write_decisions(at)
        self._log_offline_nodes(at)

    def _poll_due(self, due: list[SensorBinding], now_monotonic: float) -> datetime:
        results = {r.sensor: r for r in poll_all([(b.slug, b.driver) for b in due])}
        at = self.now()
        for binding in due:
            self._last_polled[binding.slug] = now_monotonic
            result = results[binding.slug]
            if not result.ok:
                logger.warning(
                    "sensor %s failed after %d attempt(s): %s",
                    binding.slug,
                    result.attempts,
                    result.error,
                )
                continue
            self.repo.touch_node(binding.node, at)
            for sample in result.samples:
                channel_id = binding.channel_ids.get(sample.key)
                if channel_id is not None:
                    self.repo.insert_reading(
                        Reading(
                            channel_id=channel_id,
                            at=at,
                            value=sample.value,
                            quality=sample.quality,
                        )
                    )
        return at

    def _update_derived_vpd(self, at: datetime) -> None:
        for zone in self.config.zones:
            vpd_channel_id = self.vpd_channel_ids.get(zone.slug)
            if vpd_channel_id is None:
                continue
            roles = self.repo.channels_by_role(zone.slug)
            temp_id = roles.get(ChannelRole.AIR_TEMP)
            humidity_id = roles.get(ChannelRole.HUMIDITY)
            if temp_id is None or humidity_id is None:
                continue
            temp = self.repo.latest_value(temp_id)
            humidity = self.repo.latest_value(humidity_id)
            if temp is None or humidity is None:
                continue
            vpd = vapour_pressure_deficit(temp[0], humidity[0])
            self.repo.insert_reading(
                Reading(
                    channel_id=vpd_channel_id, at=at, value=vpd, quality=Quality.DERIVED
                )
            )

    def _write_decisions(self, at: datetime) -> None:
        for zone in self.config.zones:
            roles = self.repo.channels_by_role(zone.slug)
            observed: dict[str, float] = {}
            for role, channel_id in roles.items():
                latest = self.repo.latest_value(channel_id)
                if latest is not None:
                    observed[role.value] = latest[0]

            if not observed:
                decision = Decision(
                    at=at,
                    zone=zone.slug,
                    kind=DecisionKind.INSUFFICIENT_DATA,
                    reason="no reading has arrived yet for this zone",
                )
            else:
                summary = ", ".join(f"{k}={v:.1f}" for k, v in sorted(observed.items()))
                decision = Decision(
                    at=at,
                    zone=zone.slug,
                    kind=DecisionKind.NO_ACTION,
                    reason=f"automation disabled (stage A); observed {summary}",
                    inputs=observed,
                )
            self.repo.insert_decision(decision)

    def _log_offline_nodes(self, at: datetime) -> None:
        for node in self.config.nodes:
            last_seen = self.repo.last_seen(node.slug)
            health = NodeHealth(
                node=node.slug,
                last_seen_at=last_seen,
                stale_after_seconds=node.stale_after_seconds,
            )
            if health.is_stale(at):
                logger.warning("node %s is offline (last seen %s)", node.slug, last_seen)

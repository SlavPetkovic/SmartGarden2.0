"""Derived channels the loop computes itself, not any driver (CTRL-10, ML-1).

VPD needs a channel row to be stored as an ordinary reading (DATA-1) even
though no physical sensor produces it. One virtual sensor per zone keeps it
bound to that zone the same way a real channel would be, and keeps
`channel.sensor_id NOT NULL` true without a schema change.
"""

from __future__ import annotations

from collections.abc import Sequence

from smartgarden.core.models import ChannelRole, ChannelSpec
from smartgarden.storage.repository import Repository

__all__ = ["DERIVED_NODE_SLUG", "derived_sensor_slug", "ensure_derived_channels"]

DERIVED_NODE_SLUG = "derived"

_VPD_SPEC = ChannelSpec(
    key="vpd", unit="kPa", role=ChannelRole.VPD, precision=3, plausible_min=0.0
)


def derived_sensor_slug(zone: str) -> str:
    return f"derived-{zone}"


def ensure_derived_channels(repo: Repository, zones: Sequence[str]) -> dict[str, int]:
    """One virtual sensor per zone with a `vpd` channel. Returns zone -> channel_id.

    Idempotent, like every other reconciliation in this codebase: calling it
    again on a later startup upserts the same rows rather than duplicating.
    """
    if not zones:
        return {}

    repo.upsert_node(
        DERIVED_NODE_SLUG,
        kind="derived",
        description="Computed channels (VPD, ...) -- not a physical bus",
        stale_after_seconds=float("inf"),
    )

    result: dict[str, int] = {}
    for zone in zones:
        slug = derived_sensor_slug(zone)
        repo.upsert_sensor(
            slug, node=DERIVED_NODE_SLUG, driver="derived", interval_seconds=1.0
        )
        channel_ids = repo.reconcile_channels(slug, [_VPD_SPEC], zone=zone)
        result[zone] = channel_ids["vpd"]
    return result

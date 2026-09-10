"""The API routes (API-1...4, ARCH-2, ARCH-3, ARCH-6).

Every handler goes through `Repository` -- nothing here opens a raw
connection or names a table -- and nothing here imports from
`smartgarden.drivers` or `smartgarden.runtime`: the web process cannot
touch GPIO or I2C because it holds no code path that could (ARCH-2, ARCH-3).
A manual action becomes a `commands` row, exactly like every other command;
the control loop is the only thing that ever drains it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from smartgarden.core.errors import StorageError
from smartgarden.core.models import (
    ChannelRole,
    ChannelSpec,
    Command,
    CommandKind,
    Quality,
    Reading,
)
from smartgarden.storage.repository import Repository
from smartgarden.web.auth import require_token
from smartgarden.web.deps import get_repo
from smartgarden.web.schemas import (
    ChannelOut,
    CommandIn,
    CommandOut,
    IngestRequest,
    IngestResponse,
    ReadingPointOut,
    RollupPointOut,
    TimeSeriesOut,
)
from smartgarden.web.timeseries import pick_tier

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_token)])

RepoDep = Annotated[Repository, Depends(get_repo)]


@router.get("/channels", response_model=list[ChannelOut])
def list_channels(repo: RepoDep) -> list[ChannelOut]:
    """Channel and role metadata (API-2): a new sensor appears here with no
    front-end change, because nothing here names a driver or a sensor type."""
    return [
        ChannelOut(
            id=c.id,
            sensor=c.sensor,
            key=c.key,
            unit=c.unit,
            role=c.role.value if c.role is not None else None,
            precision=c.precision,
            plausible_min=c.plausible_min,
            plausible_max=c.plausible_max,
            zone=c.zone,
            plant=c.plant,
        )
        for c in repo.all_channels()
    ]


@router.get("/channels/{channel_id}/timeseries", response_model=TimeSeriesOut)
def timeseries(
    channel_id: int, start: datetime, end: datetime, repo: RepoDep
) -> TimeSeriesOut:
    """Raw or rolled-up points, tier chosen from the requested range (API-3)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "start and end must be timezone-aware")
    if end <= start:
        raise HTTPException(422, "end must be after start")

    tier = pick_tier(start, end)
    if tier == "raw":
        raw_points = repo.readings_between(channel_id, start, end)
        return TimeSeriesOut(
            channel_id=channel_id,
            tier=tier,
            start=start,
            end=end,
            raw=[
                ReadingPointOut(ts=p.at, value=p.value, quality=p.quality.value)
                for p in raw_points
            ],
        )

    buckets = repo.rollup_between(channel_id, tier, start, end)
    return TimeSeriesOut(
        channel_id=channel_id,
        tier=tier,
        start=start,
        end=end,
        rollup=[
            RollupPointOut(
                ts=b.bucket_start,
                min=b.min_value,
                max=b.max_value,
                mean=b.mean_value,
                count=b.sample_count,
            )
            for b in buckets
        ],
    )


@router.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest(payload: IngestRequest, repo: RepoDep) -> IngestResponse:
    """External readings, normalised the same way a local driver's
    `channels()` declaration would be (ARCH-6): once accepted, an ingested
    reading is indistinguishable downstream from one the local bus produced."""
    repo.upsert_node(
        payload.node,
        kind=payload.node_kind,
        stale_after_seconds=payload.stale_after_seconds,
    )
    repo.upsert_sensor(
        payload.sensor,
        node=payload.node,
        driver=payload.driver,
        interval_seconds=payload.interval_seconds,
    )
    specs = [
        ChannelSpec(
            key=c.key,
            unit=c.unit,
            role=ChannelRole(c.role) if c.role is not None else None,
            precision=c.precision,
            plausible_min=c.plausible_min,
            plausible_max=c.plausible_max,
        )
        for c in payload.channels
    ]
    try:
        channel_ids = repo.reconcile_channels(
            payload.sensor, specs, zone=payload.zone, plant=payload.plant
        )
    except StorageError as exc:
        raise HTTPException(404, str(exc)) from exc

    for reading in payload.readings:
        if reading.key not in channel_ids:
            raise HTTPException(
                422,
                f"reading key '{reading.key}' was not declared in this payload",
            )
        repo.insert_reading(
            Reading(
                channel_id=channel_ids[reading.key],
                at=payload.at,
                value=reading.value,
                quality=Quality(reading.quality),
            )
        )
    repo.touch_node(payload.node, payload.at)

    logger.info(
        "ingested %d reading(s) from node=%s sensor=%s",
        len(payload.readings),
        payload.node,
        payload.sensor,
    )
    return IngestResponse(accepted=len(payload.readings))


@router.post("/zones/{zone}/commands", response_model=CommandOut, status_code=201)
def create_command(zone: str, payload: CommandIn, repo: RepoDep) -> CommandOut:
    """A manual action, queued as a `commands` row (ARCH-3): the control loop
    drains it through the same guards as anything automatic. This process
    never drives a device directly."""
    try:
        kind = CommandKind(payload.kind)
    except ValueError as exc:
        known = ", ".join(sorted(k.value for k in CommandKind))
        raise HTTPException(
            422, f"unknown command kind '{payload.kind}'. Known: {known}"
        ) from exc

    at = datetime.now(UTC)
    command = Command(
        id=0,
        at=at,
        kind=kind,
        zone=zone,
        duration_seconds=payload.duration_seconds,
        issued_by=payload.issued_by,
    )
    try:
        command_id = repo.insert_command(command)
    except StorageError as exc:
        raise HTTPException(404, str(exc)) from exc

    return CommandOut(
        id=command_id,
        at=at,
        kind=kind.value,
        zone=zone,
        duration_seconds=payload.duration_seconds,
        issued_by=payload.issued_by,
        pending=True,
    )


@router.get("/commands", response_model=list[CommandOut])
def list_pending_commands(repo: RepoDep) -> list[CommandOut]:
    return [
        CommandOut(
            id=c.id,
            at=c.at,
            kind=c.kind.value,
            zone=c.zone,
            duration_seconds=c.duration_seconds,
            issued_by=c.issued_by,
            pending=c.pending,
        )
        for c in repo.pending_commands()
    ]

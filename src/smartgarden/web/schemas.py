"""Request and response bodies (API-1: JSON only, nothing templated).

Pydantic models here mirror core dataclasses field-for-field rather than
re-exporting them directly, so a wire-format decision (should quality be a
string? should a role be omitted when absent?) never has to double as a
decision about the internal domain model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "ChannelOut",
    "CommandIn",
    "CommandOut",
    "IngestChannel",
    "IngestReading",
    "IngestRequest",
    "IngestResponse",
    "RollupPointOut",
    "TimeSeriesOut",
]


class ChannelOut(BaseModel):
    id: int
    sensor: str
    key: str
    unit: str
    role: str | None
    precision: int
    plausible_min: float | None
    plausible_max: float | None
    zone: str | None
    plant: str | None


class RollupPointOut(BaseModel):
    ts: datetime
    min: float
    max: float
    mean: float
    count: int


class ReadingPointOut(BaseModel):
    ts: datetime
    value: float
    quality: str


class TimeSeriesOut(BaseModel):
    channel_id: int
    tier: str
    start: datetime
    end: datetime
    raw: list[ReadingPointOut] = Field(default_factory=list)
    rollup: list[RollupPointOut] = Field(default_factory=list)


class CommandIn(BaseModel):
    kind: str
    duration_seconds: float | None = None
    issued_by: str = "ui"


class CommandOut(BaseModel):
    id: int
    at: datetime
    kind: str
    zone: str | None
    duration_seconds: float | None
    issued_by: str
    pending: bool


class IngestChannel(BaseModel):
    key: str
    unit: str
    role: str | None = None
    precision: int = 2
    plausible_min: float | None = None
    plausible_max: float | None = None


class IngestReading(BaseModel):
    key: str
    value: float
    quality: str = "ok"


class IngestRequest(BaseModel):
    """The normalised shape a remote node ships (ARCH-6).

    Deliberately self-describing: a remote node names its own node, sensor,
    driver and channel declarations on the wire, the same information a
    local driver's `channels()` would supply in-process. Downstream, an
    ingested reading is indistinguishable from a local one -- same tables,
    same role resolution, same time-series endpoint.
    """

    node: str
    node_kind: str = "remote"
    stale_after_seconds: float = 180.0
    sensor: str
    driver: str
    interval_seconds: float = 60.0
    zone: str | None = None
    plant: str | None = None
    at: datetime
    channels: list[IngestChannel]
    readings: list[IngestReading]


class IngestResponse(BaseModel):
    accepted: int

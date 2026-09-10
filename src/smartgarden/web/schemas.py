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
    "ActuationOut",
    "ChannelOut",
    "CommandIn",
    "CommandOut",
    "DecisionOut",
    "HealthOut",
    "IngestChannel",
    "IngestReading",
    "IngestRequest",
    "IngestResponse",
    "NodeOut",
    "PlantOut",
    "PlantUpdate",
    "RollupPointOut",
    "SensorOut",
    "TimeSeriesOut",
    "ZoneOut",
    "ZoneUpdate",
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


class PlantOut(BaseModel):
    slug: str
    name: str
    zone: str
    species: str
    location: str
    moisture_low: float | None
    moisture_high: float | None
    dli_target_moles: float | None
    photoperiod_start_hour: int | None
    photoperiod_end_hour: int | None
    notes: str


class PlantUpdate(BaseModel):
    """UI-3: thresholds and targets, editable from the UI, writing to the
    database -- never to config/plants.toml. Any field left out of the
    request body is left unchanged; a field explicitly sent as null clears it."""

    moisture_low: float | None = None
    moisture_high: float | None = None
    dli_target_moles: float | None = None
    photoperiod_start_hour: int | None = None
    photoperiod_end_hour: int | None = None
    notes: str | None = None


class ZoneOut(BaseModel):
    slug: str
    name: str
    timezone: str
    watering_start_hour: int
    watering_end_hour: int
    daily_budget_seconds: float
    max_pulses_per_hour: int
    cooldown_seconds: float
    settle_seconds: float
    enabled: bool


class ZoneUpdate(BaseModel):
    """UI-3: windows and budgets, editable from the UI. Same partial-update
    semantics as PlantUpdate."""

    watering_start_hour: int | None = None
    watering_end_hour: int | None = None
    daily_budget_seconds: float | None = None
    max_pulses_per_hour: int | None = None
    cooldown_seconds: float | None = None
    settle_seconds: float | None = None
    enabled: bool | None = None


class NodeOut(BaseModel):
    slug: str
    kind: str
    description: str
    last_seen_at: datetime | None
    online: bool


class SensorOut(BaseModel):
    slug: str
    node: str
    driver: str
    address: int | None
    mux_address: int | None
    mux_channel: int | None
    interval_seconds: float
    enabled: bool


class HealthOut(BaseModel):
    nodes: list[NodeOut]
    sensors: list[SensorOut]


class DecisionOut(BaseModel):
    at: datetime
    zone: str
    kind: str
    action: str | None
    duration_seconds: float | None
    reason: str
    inputs: dict[str, float]


class ActuationOut(BaseModel):
    """UI-6: irrigation events marked on a chart's time axis. Empty in stage
    A -- nothing can act yet -- populated once layer 04b exists."""

    at: datetime
    device: str
    action: str
    state: str
    commanded_seconds: float | None
    actual_seconds: float | None
    pre_value: float | None
    post_value: float | None

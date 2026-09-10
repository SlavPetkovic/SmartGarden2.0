"""Rollups: downsampled tiers built from finer data (STOR-2, STOR-3).

Two tiers, each computed from the tier immediately below it: `minute` from
raw readings, `quarter_hour` from `minute` rollups. Re-running a job over a
window it has already covered replaces those bucket rows rather than adding
to them -- `INSERT ... ON CONFLICT DO UPDATE` keyed on
`(channel, tier, bucket_start)` -- which is what makes it safe to schedule
with generous overlap instead of exact boundaries (STOR-2).

Storing min, max, mean and count rather than just mean is what lets a
quarter-hour bucket be built correctly from twelve minute buckets: the mean is
weighted by each input's own count, and min/max fold rather than average
(STOR-3).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from smartgarden.storage.timeutil import from_iso, to_iso

__all__ = ["Tier", "run_rollup"]


class Tier(StrEnum):
    MINUTE = "minute"
    QUARTER_HOUR = "quarter_hour"


_BUCKET_SECONDS: dict[Tier, int] = {
    Tier.MINUTE: 60,
    Tier.QUARTER_HOUR: 15 * 60,
}

# (channel_id, source timestamp, min, max, mean, count)
_SourceRow = tuple[int, str, float, float, float, int]


@dataclass(slots=True)
class _Bucket:
    min_value: float
    max_value: float
    weighted_sum: float
    count: int

    @property
    def mean(self) -> float:
        return self.weighted_sum / self.count


def _floor(at: datetime, bucket_seconds: int) -> datetime:
    epoch = int(at.timestamp())
    floored = epoch - (epoch % bucket_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


def _source_rows(
    conn: sqlite3.Connection, tier: Tier, since: datetime, until: datetime
) -> Iterable[_SourceRow]:
    """Rows feeding this tier: raw readings for `minute`, minute rollups for
    `quarter_hour`. Each already carries (or trivially is) min/max/mean/count.
    """
    if tier is Tier.MINUTE:
        raw = conn.execute(
            "SELECT channel_id, ts, value FROM reading WHERE ts >= ? AND ts < ?",
            (to_iso(since), to_iso(until)),
        ).fetchall()
        return [
            (
                int(r["channel_id"]),
                r["ts"],
                float(r["value"]),
                float(r["value"]),
                float(r["value"]),
                1,
            )
            for r in raw
        ]

    source = conn.execute(
        """
        SELECT
            channel_id, bucket_start AS ts, min_value, max_value, mean_value, sample_count
        FROM reading_rollup
        WHERE tier = ? AND bucket_start >= ? AND bucket_start < ?
        """,
        (Tier.MINUTE.value, to_iso(since), to_iso(until)),
    ).fetchall()
    return [
        (
            int(r["channel_id"]),
            r["ts"],
            float(r["min_value"]),
            float(r["max_value"]),
            float(r["mean_value"]),
            int(r["sample_count"]),
        )
        for r in source
    ]


def run_rollup(
    conn: sqlite3.Connection, tier: Tier, since: datetime, until: datetime
) -> int:
    """Aggregate the tier below `tier` into it, over `[since, until)`.

    Returns the number of bucket rows written. Calling this twice over the
    same window with unchanged source data writes the same rows both times.
    """
    bucket_seconds = _BUCKET_SECONDS[tier]
    buckets: dict[tuple[int, datetime], _Bucket] = {}

    for channel_id, ts, min_v, max_v, mean_v, count in _source_rows(
        conn, tier, since, until
    ):
        bucket_start = _floor(from_iso(ts), bucket_seconds)
        key = (channel_id, bucket_start)
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = _Bucket(
                min_value=min_v, max_value=max_v, weighted_sum=mean_v * count, count=count
            )
            continue
        bucket.min_value = min(bucket.min_value, min_v)
        bucket.max_value = max(bucket.max_value, max_v)
        bucket.weighted_sum += mean_v * count
        bucket.count += count

    for (channel_id, bucket_start), bucket in buckets.items():
        conn.execute(
            """
            INSERT INTO reading_rollup (
                channel_id, tier, bucket_start,
                min_value, max_value, mean_value, sample_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (channel_id, tier, bucket_start) DO UPDATE SET
                min_value = excluded.min_value,
                max_value = excluded.max_value,
                mean_value = excluded.mean_value,
                sample_count = excluded.sample_count
            """,
            (
                channel_id,
                tier.value,
                to_iso(bucket_start),
                bucket.min_value,
                bucket.max_value,
                bucket.mean,
                bucket.count,
            ),
        )

    return len(buckets)

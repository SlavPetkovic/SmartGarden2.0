"""Reading many sensors without one dead one stalling the rest (SENS-2, SENS-3).

`poll_all` is what `smartgarden run` (layer 04a) will call every tick. It
retries a failing driver with backoff, records the failure against that
sensor rather than raising, and grades every value it does get against the
driver's own declared plausible range -- out of range is stored flagged, not
dropped and not trusted.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelSpec, Quality, Sample
from smartgarden.drivers.base import SensorDriver

__all__ = ["SensorReadResult", "poll_all"]

DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (0.1, 0.5, 2.0)


@dataclass(frozen=True, slots=True)
class SensorReadResult:
    sensor: str
    samples: tuple[Sample, ...] = ()
    error: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.error is None


def poll_all(
    sensors: Sequence[tuple[str, SensorDriver]],
    *,
    max_attempts: int = 3,
    backoff_seconds: Sequence[float] = DEFAULT_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[SensorReadResult]:
    """Read every sensor, retrying failures independently of one another.

    A driver that always raises produces one failed `SensorReadResult` and
    every other sensor still gets read -- this is the loop-stall guard
    (SENS-2). `sleep` is injectable so a test never actually waits out a
    real backoff.
    """
    return [
        _read_one(slug, driver, max_attempts, backoff_seconds, sleep)
        for slug, driver in sensors
    ]


def _read_one(
    slug: str,
    driver: SensorDriver,
    max_attempts: int,
    backoff_seconds: Sequence[float],
    sleep: Callable[[float], None],
) -> SensorReadResult:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            samples = _classify(driver, driver.read())
            return SensorReadResult(sensor=slug, samples=samples, attempts=attempt)
        except (SensorError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt < max_attempts and backoff_seconds:
                delay = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
                sleep(delay)
    return SensorReadResult(sensor=slug, error=last_error, attempts=max_attempts)


def _classify(driver: SensorDriver, samples: Sequence[Sample]) -> tuple[Sample, ...]:
    """Grade each sample against its channel's declared plausible range.

    A sample that already carries a non-OK quality (a driver that knows its
    own reading was suspect) is left alone -- classification only ever
    downgrades OK, it never overrides a driver's own judgement.
    """
    specs: dict[str, ChannelSpec] = {spec.key: spec for spec in driver.channels()}
    graded: list[Sample] = []
    for sample in samples:
        spec = specs.get(sample.key)
        quality = sample.quality
        if spec is not None and quality is Quality.OK:
            quality = spec.classify(sample.value)
        graded.append(Sample(key=sample.key, value=sample.value, quality=quality))
    return tuple(graded)

"""One dead sensor does not stall the others, and out-of-range values are
flagged rather than dropped (SENS-2, SENS-3)."""

from __future__ import annotations

import unittest
from collections.abc import Sequence

from smartgarden.core.errors import SensorError
from smartgarden.core.models import ChannelSpec, Quality, Sample
from smartgarden.drivers.polling import poll_all


class WorkingSensor:
    def __init__(self, value: float = 42.0) -> None:
        self._value = value

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (ChannelSpec(key="x", unit="u", plausible_min=0.0, plausible_max=100.0),)

    def read(self) -> Sequence[Sample]:
        return (Sample(key="x", value=self._value),)


class AlwaysFailingSensor:
    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (ChannelSpec(key="x", unit="u"),)

    def read(self) -> Sequence[Sample]:
        raise SensorError("simulated permanent failure")


class FailsOnceSensor:
    def __init__(self) -> None:
        self._calls = 0

    @classmethod
    def channels(cls) -> Sequence[ChannelSpec]:
        return (ChannelSpec(key="x", unit="u"),)

    def read(self) -> Sequence[Sample]:
        self._calls += 1
        if self._calls == 1:
            raise SensorError("transient blip")
        return (Sample(key="x", value=7.0),)


class TestPollAll(unittest.TestCase):
    def setUp(self) -> None:
        self.sleeps: list[float] = []

    def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def test_one_always_failing_sensor_does_not_stop_the_others(self) -> None:
        results = poll_all(
            [
                ("good-1", WorkingSensor(1.0)),
                ("bad", AlwaysFailingSensor()),
                ("good-2", WorkingSensor(2.0)),
            ],
            sleep=self._sleep,
        )
        by_slug = {r.sensor: r for r in results}

        self.assertTrue(by_slug["good-1"].ok)
        self.assertEqual(by_slug["good-1"].samples[0].value, 1.0)
        self.assertTrue(by_slug["good-2"].ok)
        self.assertEqual(by_slug["good-2"].samples[0].value, 2.0)

        self.assertFalse(by_slug["bad"].ok)
        self.assertIn("simulated permanent failure", by_slug["bad"].error or "")
        self.assertEqual(by_slug["bad"].samples, ())

    def test_failing_sensor_is_retried_before_being_recorded_as_failed(self) -> None:
        results = poll_all(
            [("bad", AlwaysFailingSensor())], max_attempts=3, sleep=self._sleep
        )
        self.assertEqual(results[0].attempts, 3)
        self.assertEqual(
            len(self.sleeps), 2
        )  # backoff between attempts 1->2 and 2->3, not after the last

    def test_recovers_on_a_later_attempt(self) -> None:
        results = poll_all(
            [("flaky", FailsOnceSensor())], max_attempts=3, sleep=self._sleep
        )
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].attempts, 2)
        self.assertEqual(results[0].samples[0].value, 7.0)

    def test_out_of_range_value_is_flagged_not_dropped(self) -> None:
        results = poll_all([("hot", WorkingSensor(999.0))], sleep=self._sleep)
        self.assertTrue(results[0].ok)  # a bad reading is not a failed read
        sample = results[0].samples[0]
        self.assertEqual(sample.value, 999.0)
        self.assertIs(sample.quality, Quality.OUT_OF_RANGE)

    def test_in_range_value_is_ok(self) -> None:
        results = poll_all([("fine", WorkingSensor(50.0))], sleep=self._sleep)
        self.assertIs(results[0].samples[0].quality, Quality.OK)


if __name__ == "__main__":
    unittest.main()

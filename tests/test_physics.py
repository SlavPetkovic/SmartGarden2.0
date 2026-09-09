"""Tests for atmospheric and horticultural physics.

Expected values are cross-checked against published psychrometric tables rather
than against this implementation, so a transcription error in a constant fails
here instead of quietly biasing every irrigation decision.

Written against unittest so the suite runs with no dependencies at all; pytest
collects these classes unchanged.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from smartgarden.core.physics import (
    DliAccumulator,
    absolute_humidity,
    actual_vapour_pressure,
    dew_point,
    dli_increment,
    lux_to_ppfd,
    pressure_to_altitude,
    relative_humidity_from_dew_point,
    saturation_vapour_pressure,
    vapour_pressure_deficit,
)


class TestSaturationVapourPressure(unittest.TestCase):
    # (celsius, kPa) from standard psychrometric tables.
    TABLE = ((0.0, 0.611), (10.0, 1.228), (20.0, 2.339), (25.0, 3.169), (30.0, 4.246))

    def test_matches_published_table(self) -> None:
        for celsius, expected in self.TABLE:
            with self.subTest(celsius=celsius):
                self.assertAlmostEqual(
                    saturation_vapour_pressure(celsius), expected, delta=expected * 0.01
                )

    def test_rises_monotonically(self) -> None:
        values = [saturation_vapour_pressure(t) for t in range(-10, 45, 5)]
        self.assertEqual(values, sorted(values))

    def test_is_convex_in_temperature(self) -> None:
        # Tripling temperature more than doubles capacity -- the reason warm air
        # dries soil disproportionately fast.
        self.assertGreater(
            saturation_vapour_pressure(30), 2 * saturation_vapour_pressure(10)
        )


class TestVapourPressureDeficit(unittest.TestCase):
    def test_zero_at_saturation(self) -> None:
        self.assertAlmostEqual(vapour_pressure_deficit(22.0, 100.0), 0.0, places=9)

    def test_equals_saturation_in_bone_dry_air(self) -> None:
        self.assertAlmostEqual(
            vapour_pressure_deficit(22.0, 0.0), saturation_vapour_pressure(22.0), places=9
        )

    def test_known_value(self) -> None:
        # 25 C / 50% RH is the textbook worked example: about 1.58 kPa.
        self.assertAlmostEqual(vapour_pressure_deficit(25.0, 50.0), 1.58, delta=0.04)

    def test_same_humidity_higher_temperature_means_higher_deficit(self) -> None:
        """The whole reason VPD beats relative humidity as a drying predictor."""
        cool = vapour_pressure_deficit(15.0, 60.0)
        warm = vapour_pressure_deficit(30.0, 60.0)
        self.assertGreater(warm, cool * 2)

    def test_is_es_minus_ea(self) -> None:
        es = saturation_vapour_pressure(18.5)
        ea = actual_vapour_pressure(18.5, 42.0)
        self.assertAlmostEqual(vapour_pressure_deficit(18.5, 42.0), es - ea, places=9)

    def test_rejects_impossible_humidity(self) -> None:
        for humidity in (-1.0, 100.1, 500.0):
            with self.subTest(humidity=humidity), self.assertRaises(ValueError):
                vapour_pressure_deficit(20.0, humidity)


class TestDewPoint(unittest.TestCase):
    TABLE = ((25.0, 50.0, 13.86), (20.0, 80.0, 16.44), (30.0, 30.0, 10.50))

    def test_matches_published_table(self) -> None:
        for celsius, humidity, expected in self.TABLE:
            with self.subTest(celsius=celsius, humidity=humidity):
                self.assertAlmostEqual(dew_point(celsius, humidity), expected, delta=0.15)

    def test_equals_air_temperature_at_saturation(self) -> None:
        self.assertAlmostEqual(dew_point(17.3, 100.0), 17.3, places=6)

    def test_never_exceeds_air_temperature(self) -> None:
        for temp in (5.0, 20.0, 35.0):
            for humidity in (10.0, 50.0, 99.0):
                with self.subTest(temp=temp, humidity=humidity):
                    self.assertLessEqual(dew_point(temp, humidity), temp)

    def test_undefined_at_zero_humidity(self) -> None:
        with self.assertRaisesRegex(ValueError, "undefined"):
            dew_point(20.0, 0.0)

    def test_round_trips_through_relative_humidity(self) -> None:
        td = dew_point(24.0, 55.0)
        self.assertAlmostEqual(
            relative_humidity_from_dew_point(24.0, td), 55.0, delta=0.1
        )

    def test_relative_humidity_rejects_impossible_dew_point(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            relative_humidity_from_dew_point(15.0, 20.0)


class TestAbsoluteHumidity(unittest.TestCase):
    def test_known_value(self) -> None:
        # ~23 g/m3 at saturation and 25 C, so about 11.5 at half that.
        self.assertAlmostEqual(absolute_humidity(25.0, 50.0), 11.5, delta=0.4)

    def test_vapour_pressure_is_conserved_as_air_warms(self) -> None:
        """Heating air without adding water leaves vapour pressure unchanged
        while relative humidity falls -- the reason a heated room feels dry."""
        ea_cold = actual_vapour_pressure(10.0, 80.0)
        td = dew_point(10.0, 80.0)
        rh_warm = relative_humidity_from_dew_point(25.0, td)
        self.assertAlmostEqual(actual_vapour_pressure(25.0, rh_warm), ea_cold, places=6)
        self.assertLess(rh_warm, 80.0)

    def test_density_falls_as_air_expands(self) -> None:
        """Absolute humidity is mass per *volume*, so it is NOT conserved on
        warming: the same water occupies a larger volume.

        It scales as 1/T in kelvin. The conserved quantity is the mixing ratio
        (g/kg), which is a different metric. Worth pinning down, because
        "absolute humidity is conserved" is a common and plausible-sounding
        error that would put a systematic bias into any drying model built on it.
        """
        ah_cold = absolute_humidity(10.0, 80.0)
        td = dew_point(10.0, 80.0)
        rh_warm = relative_humidity_from_dew_point(25.0, td)
        expected_ratio = (10.0 + 273.15) / (25.0 + 273.15)
        self.assertAlmostEqual(
            absolute_humidity(25.0, rh_warm) / ah_cold, expected_ratio, places=4
        )


class TestLight(unittest.TestCase):
    def test_daylight_conversion(self) -> None:
        self.assertAlmostEqual(lux_to_ppfd(10_000.0), 185.2, delta=1.0)

    def test_fixture_factor_is_applied(self) -> None:
        self.assertAlmostEqual(lux_to_ppfd(7500.0, lux_per_ppfd=75.0), 100.0, places=9)

    def test_darkness_is_zero(self) -> None:
        self.assertEqual(lux_to_ppfd(0.0), 0.0)

    def test_rejects_negative_lux(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative"):
            lux_to_ppfd(-1.0)

    def test_rejects_zero_conversion_factor(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            lux_to_ppfd(100.0, 0.0)

    def test_dli_increment_over_twelve_hours(self) -> None:
        # 200 umol/m2/s for 12h is 8.64 mol/m2 -- a standard worked example.
        self.assertAlmostEqual(dli_increment(200.0, 12 * 3600), 8.64, places=9)

    def test_dli_increment_is_linear(self) -> None:
        self.assertAlmostEqual(
            dli_increment(100.0, 7200), 2 * dli_increment(100.0, 3600), places=9
        )


class TestPressureToAltitude(unittest.TestCase):
    def test_sea_level_is_zero(self) -> None:
        self.assertAlmostEqual(pressure_to_altitude(101.325), 0.0, delta=0.5)

    def test_lower_pressure_is_higher(self) -> None:
        self.assertGreater(pressure_to_altitude(90.0), pressure_to_altitude(100.0))

    def test_rejects_nonsense(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            pressure_to_altitude(0.0)


class TestDliAccumulator(unittest.TestCase):
    BASE = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)

    def at(self, minutes: float) -> datetime:
        return self.BASE + timedelta(minutes=minutes)

    def test_starts_empty(self) -> None:
        self.assertEqual(DliAccumulator().moles, 0.0)

    def test_first_sample_only_anchors_the_clock(self) -> None:
        acc = DliAccumulator().observe(500.0, self.at(0), "2026-06-01")
        self.assertEqual(acc.moles, 0.0)
        self.assertEqual(acc.last_at, self.at(0))

    def test_accumulates_across_samples(self) -> None:
        acc = DliAccumulator()
        for minute in range(0, 61):
            acc = acc.observe(300.0, self.at(minute), "2026-06-01")
        # 300 umol/m2/s for one hour = 1.08 mol/m2
        self.assertAlmostEqual(acc.moles, 1.08, delta=0.01)

    def test_resets_on_day_change(self) -> None:
        acc = DliAccumulator()
        acc = acc.observe(400.0, self.at(0), "2026-06-01")
        acc = acc.observe(400.0, self.at(4), "2026-06-01")
        self.assertGreater(acc.moles, 0)
        acc = acc.observe(400.0, self.at(8), "2026-06-02")
        self.assertEqual(acc.moles, 0.0)
        self.assertEqual(acc.local_day, "2026-06-02")

    def test_long_gap_contributes_nothing(self) -> None:
        """A restart or stalled sensor must not integrate as steady light."""
        acc = DliAccumulator().observe(800.0, self.at(0), "2026-06-01")
        acc = acc.observe(800.0, self.at(120), "2026-06-01", max_gap_seconds=300.0)
        self.assertEqual(acc.moles, 0.0)
        self.assertEqual(acc.last_at, self.at(120))

    def test_is_immutable(self) -> None:
        first = DliAccumulator().observe(100.0, self.at(0), "2026-06-01")
        second = first.observe(100.0, self.at(1), "2026-06-01")
        self.assertEqual(first.moles, 0.0)
        self.assertIsNot(second, first)

    def test_rejects_naive_timestamps(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            DliAccumulator().observe(100.0, datetime(2026, 6, 1, 6, 0), "2026-06-01")

    def test_shortfall_never_negative(self) -> None:
        acc = DliAccumulator(moles=12.0)
        self.assertEqual(acc.shortfall(6.0), 0.0)
        self.assertAlmostEqual(acc.shortfall(20.0), 8.0, places=9)

    def test_supplement_seconds_closes_the_gap(self) -> None:
        acc = DliAccumulator(moles=4.0)
        seconds = acc.seconds_of_supplement_needed(6.0, fixture_ppfd=120.0)
        # Running that long must deliver exactly the shortfall.
        self.assertAlmostEqual(dli_increment(120.0, seconds), 2.0, places=9)

    def test_no_supplement_when_target_met(self) -> None:
        self.assertEqual(
            DliAccumulator(moles=9.0).seconds_of_supplement_needed(6.0, 120.0), 0.0
        )

    def test_unlit_fixture_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            DliAccumulator(moles=1.0).seconds_of_supplement_needed(6.0, 0.0)


if __name__ == "__main__":
    unittest.main()

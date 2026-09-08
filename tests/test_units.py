"""Tests for unit conversion and display formatting."""

from __future__ import annotations

import unittest

from smartgarden.core.units import (
    TemperatureUnit,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    format_duration,
    format_temperature,
    hpa_to_kpa,
    kpa_to_hpa,
)


class TestTemperature(unittest.TestCase):
    PAIRS = [(0.0, 32.0), (100.0, 212.0), (-40.0, -40.0), (21.0, 69.8)]

    def test_conversion(self) -> None:
        for celsius, fahrenheit in self.PAIRS:
            with self.subTest(celsius=celsius):
                self.assertAlmostEqual(celsius_to_fahrenheit(celsius), fahrenheit, places=6)
                self.assertAlmostEqual(fahrenheit_to_celsius(fahrenheit), celsius, places=6)

    def test_round_trips(self) -> None:
        for c in (-15.5, 0.0, 22.3, 38.9):
            with self.subTest(c=c):
                self.assertAlmostEqual(fahrenheit_to_celsius(celsius_to_fahrenheit(c)), c, places=9)

    def test_formatting(self) -> None:
        self.assertEqual(format_temperature(21.34), "21.3°C")
        self.assertEqual(format_temperature(21.0, TemperatureUnit.FAHRENHEIT), "69.8°F")


class TestPressure(unittest.TestCase):
    def test_conversion(self) -> None:
        self.assertAlmostEqual(kpa_to_hpa(101.325), 1013.25, places=6)
        self.assertAlmostEqual(hpa_to_kpa(1013.25), 101.325, places=6)

    def test_round_trips(self) -> None:
        self.assertAlmostEqual(hpa_to_kpa(kpa_to_hpa(97.4)), 97.4, places=9)


class TestFormatDuration(unittest.TestCase):
    CASES = [
        (6.0, "6s"),
        (6.5, "6.5s"),
        (59.9, "59.9s"),
        (60.0, "1m"),
        (90.0, "1m 30s"),
        (3600.0, "1h"),
        (3720.0, "1h 2m"),
        (8040.0, "2h 14m"),
        (90000.0, "1d 1h"),
    ]

    def test_formats(self) -> None:
        for seconds, expected in self.CASES:
            with self.subTest(seconds=seconds):
                self.assertEqual(format_duration(seconds), expected)

    def test_rejects_negative(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative"):
            format_duration(-1.0)


if __name__ == "__main__":
    unittest.main()

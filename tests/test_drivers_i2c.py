"""I2CLocation: a bare address, or an address behind a mux channel (SENS-4)."""

from __future__ import annotations

import unittest

from smartgarden.drivers.i2c import I2CLocation


class TestI2CLocation(unittest.TestCase):
    def test_bare_address_is_valid(self) -> None:
        location = I2CLocation(address=0x77)
        self.assertIsNone(location.mux_address)
        self.assertIsNone(location.mux_channel)

    def test_address_behind_a_mux_channel_is_valid(self) -> None:
        location = I2CLocation(address=0x36, mux_address=0x70, mux_channel=1)
        self.assertEqual(location.mux_address, 0x70)
        self.assertEqual(location.mux_channel, 1)

    def test_mux_address_without_channel_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            I2CLocation(address=0x36, mux_address=0x70)

    def test_mux_channel_without_address_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            I2CLocation(address=0x36, mux_channel=1)


if __name__ == "__main__":
    unittest.main()

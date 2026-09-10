"""Tests for the command-line entry point."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from smartgarden.cli import main

REPO_CONFIG = str(Path(__file__).resolve().parents[1] / "config")


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestConfigCheck(unittest.TestCase):
    def test_reports_valid_repository_config(self) -> None:
        code, out, _ = run(["--config-dir", REPO_CONFIG, "config", "check"])
        self.assertEqual(code, 0)
        self.assertIn("is valid", out)
        self.assertIn("Automation is DISABLED", out)

    def test_reports_invalid_config(self) -> None:
        code, _, err = run(["--config-dir", "/nonexistent/path", "config", "check"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)


class TestPhysics(unittest.TestCase):
    def test_prints_derived_values(self) -> None:
        code, out, _ = run(["physics", "--temp", "25", "--rh", "50", "--lux", "10000"])
        self.assertEqual(code, 0)
        self.assertIn("vapour pressure deficit", out)
        self.assertIn("PPFD", out)

    def test_rejects_impossible_humidity(self) -> None:
        code, _, err = run(["physics", "--temp", "25", "--rh", "150"])
        self.assertEqual(code, 1)
        self.assertIn("0-100", err)


class TestDoctor(unittest.TestCase):
    def test_fails_cleanly_without_i2c_hardware_libraries(self) -> None:
        """On a laptop with no `[pi]` extra installed, `doctor` must report a
        clear error rather than an ImportError traceback (SENS-8)."""
        try:
            import board  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("hardware: the [pi] extra is installed in this environment")

        code, _, err = run(["--config-dir", REPO_CONFIG, "doctor"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)


class TestRun(unittest.TestCase):
    """`smartgarden run --once` against a temp config using simulated
    drivers, so it needs no I2C hardware (layer 04a)."""

    def _write_config(self, tmp: Path) -> Path:
        config_dir = tmp / "config"
        config_dir.mkdir()
        (config_dir / "app.toml").write_text(
            f'[app]\ndatabase_path = "{(tmp / "smartgarden.db").as_posix()}"\n'
            "automation_enabled = false\n",
            encoding="utf-8",
        )
        (config_dir / "sensors.toml").write_text(
            '[[node]]\nslug = "pi-local"\n\n'
            '[[sensor]]\nslug = "air-1"\nnode = "pi-local"\n'
            'driver = "simulated_bme680"\nzone = "windowsill"\n\n'
            '[[sensor]]\nslug = "soil-1"\nnode = "pi-local"\n'
            'driver = "simulated_seesaw_soil"\nzone = "windowsill"\n',
            encoding="utf-8",
        )
        (config_dir / "devices.toml").write_text(
            '[[zone]]\nslug = "windowsill"\nname = "Windowsill"\n',
            encoding="utf-8",
        )
        return config_dir

    def test_runs_a_single_tick_and_exits_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = self._write_config(Path(tmp))
            code, _, err = run(["--config-dir", str(config_dir), "run", "--once"])
            self.assertEqual(code, 0, err)


class TestPipeHandling(unittest.TestCase):
    def test_closed_pipe_is_not_an_error(self) -> None:
        """`smartgarden config check | head` must not traceback.

        A pager or `head` closing the pipe early is normal usage.
        """
        result = subprocess.run(
            f'"{sys.executable}" -m smartgarden.cli --config-dir "{REPO_CONFIG}" '
            "config check | head -3",
            shell=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path(REPO_CONFIG).parent / "src")},
        )
        self.assertNotIn("BrokenPipeError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

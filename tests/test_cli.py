"""Tests for the command-line entry point."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
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

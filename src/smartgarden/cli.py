"""Command-line entry point.

Layer 1 provided `config check` and `physics`. Layer 3 added `doctor`.
Layer 4a adds `run`. Later layers add `web`, `export` and `backup`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from smartgarden import __version__
from smartgarden.config import DEFAULT_CONFIG_DIR, load_config
from smartgarden.core.errors import SmartGardenError
from smartgarden.core.physics import (
    dew_point,
    lux_to_ppfd,
    vapour_pressure_deficit,
)
from smartgarden.drivers.doctor import ConfiguredSensor, run_doctor
from smartgarden.runtime import build_control_loop
from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartgarden",
        description="Sensor-driven irrigation and lighting for a Raspberry Pi.",
    )
    parser.add_argument(
        "--version", action="version", version=f"smartgarden {__version__}"
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        metavar="DIR",
        help=f"configuration directory (default: {DEFAULT_CONFIG_DIR})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    config_cmd = sub.add_parser("config", help="inspect configuration")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser(
        "check", help="validate the configuration and report what it describes"
    )

    physics_cmd = sub.add_parser(
        "physics", help="compute derived values from a temperature/humidity/lux triple"
    )
    physics_cmd.add_argument("--temp", type=float, required=True, metavar="C")
    physics_cmd.add_argument("--rh", type=float, required=True, metavar="PCT")
    physics_cmd.add_argument("--lux", type=float, default=None, metavar="LUX")
    physics_cmd.add_argument("--lux-per-ppfd", type=float, default=54.0)

    sub.add_parser(
        "doctor",
        help="scan the I2C bus and report each configured sensor's address",
    )

    run_cmd = sub.add_parser(
        "run", help="run the control loop in the foreground (observe-only in stage A)"
    )
    run_cmd.add_argument(
        "--once",
        action="store_true",
        help="run a single tick and exit, instead of looping",
    )

    return parser


def _cmd_config_check(config_dir: Path) -> int:
    config = load_config(config_dir)

    print(f"Configuration in {config_dir} is valid.\n")
    print(f"  nodes    {len(config.nodes)}")
    print(f"  sensors  {len(config.sensors)}")
    print(f"  zones    {len(config.zones)}")
    print(f"  devices  {len(config.devices)}")
    print(f"  plants   {len(config.plants)}")

    for zone in config.zones:
        plants = config.plants_in(zone.slug)
        devices = config.devices_in(zone.slug)
        state = "enabled" if zone.enabled else "DISABLED"
        print(f"\n  {zone.name}  [{zone.slug}, {state}]")
        print(
            f"    window {zone.watering_start_hour:02d}:00-"
            f"{zone.watering_end_hour:02d}:00 {zone.timezone}"
            f"  budget {zone.daily_budget_seconds:.0f}s/day"
            f"  max {zone.max_pulses_per_hour}/h"
        )
        for plant in plants:
            band = (
                f"{plant.moisture_low:.0f}-{plant.moisture_high:.0f}"
                if plant.moisture_low is not None and plant.moisture_high is not None
                else "not set"
            )
            print(
                f"    plant  {plant.name:<16} moisture {band:<12} "
                f"dli {plant.dli_target_moles}"
            )
        for device in devices:
            sim = "  (simulated)" if device.driver == "simulated" else ""
            print(
                f"    device {device.slug:<20} {device.kind.value:<9} "
                f"pin {device.pin} max {device.max_on_seconds:.0f}s{sim}"
            )

    if not config.app.automation_enabled:
        print(
            "\n  Automation is DISABLED (app.toml). The loop will read, store and log\n"
            "  decisions but drive nothing. Leave it this way until thresholds are\n"
            "  calibrated from real readings."
        )
    return 0


def _cmd_physics(temp: float, rh: float, lux: float | None, lux_per_ppfd: float) -> int:
    print(f"  air temperature        {temp:.2f} C")
    print(f"  relative humidity      {rh:.1f} %")
    print(f"  vapour pressure deficit {vapour_pressure_deficit(temp, rh):.3f} kPa")
    print(f"  dew point              {dew_point(temp, rh):.2f} C")
    if lux is not None:
        ppfd = lux_to_ppfd(lux, lux_per_ppfd)
        print(f"  illuminance            {lux:.0f} lux")
        print(f"  PPFD (at {lux_per_ppfd:.0f} lux/umol)  {ppfd:.1f} umol/m2/s")
        print(f"  12h at this level      {ppfd * 43200 / 1e6:.2f} mol/m2/day")
    return 0


def _cmd_doctor(config_dir: Path) -> int:
    config = load_config(config_dir)
    configured = [
        ConfiguredSensor(
            slug=sensor.slug,
            address=sensor.address,
            mux_address=sensor.mux_address,
            mux_channel=sensor.mux_channel,
        )
        for sensor in config.sensors
        if sensor.enabled and sensor.address is not None
    ]
    if not configured:
        print("No enabled sensor declares an I2C address; nothing to scan.")
        return 0

    diagnoses = run_doctor(configured)
    width = max(len(d.sensor) for d in diagnoses)
    marker = {"answered": "ok  ", "absent": "MISS", "wrong_address": "WARN"}
    failed = 0
    for d in diagnoses:
        detail = f"  {d.detail}" if d.detail else ""
        print(
            f"{marker[d.status]}  {d.sensor.ljust(width)}  "
            f"0x{d.address:02x}  {d.status}{detail}"
        )
        if d.status != "answered":
            failed += 1

    print()
    if failed:
        print(
            f"{failed} of {len(diagnoses)} sensor(s) not confirmed at their "
            "configured address."
        )
    else:
        print(f"All {len(diagnoses)} configured sensor(s) answered.")
    return 1 if failed else 0


def _cmd_run(config_dir: Path, *, once: bool) -> int:
    config = load_config(config_dir)
    logging.basicConfig(
        level=config.app.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logger = logging.getLogger("smartgarden.run")

    db_path = Path(config.app.database_path)
    if not db_path.is_absolute():
        db_path = config_dir.parent / db_path
    conn = connect(db_path)
    try:
        loop = build_control_loop(Repository(conn), config)

        logger.info(
            "control loop starting: automation_enabled=%s tick_seconds=%.1f db=%s",
            config.app.automation_enabled,
            config.app.tick_seconds,
            db_path,
        )
        if not config.app.automation_enabled:
            logger.info(
                "automation is disabled -- observing only, nothing will be driven"
            )

        loop.tick()
        if once:
            return 0

        try:
            while True:
                time.sleep(config.app.tick_seconds)
                loop.tick()
        except KeyboardInterrupt:
            logger.info("stopping on interrupt")
            return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "config":
            return _cmd_config_check(args.config_dir)
        if args.command == "physics":
            return _cmd_physics(args.temp, args.rh, args.lux, args.lux_per_ppfd)
        if args.command == "doctor":
            return _cmd_doctor(args.config_dir)
        if args.command == "run":
            return _cmd_run(args.config_dir, once=args.once)
    except BrokenPipeError:
        # Output was piped into something that closed early -- `| head`, or a
        # pager the user quit. That is normal usage, not a failure. Point the
        # remaining writes at /dev/null so the interpreter's exit-time flush
        # does not raise the same error again on the way out.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except SmartGardenError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

# SmartGarden — working notes

Sensor-driven irrigation and lighting on a Raspberry Pi 5. Read
`docs/architecture.html` before changing anything structural; it carries the
72 numbered requirements this code is written against, and the reasoning behind
the decisions below. Requirement IDs like `SAFE-1` and `DATA-3` in code comments
refer to that document.

## The one-line summary

Three plants on a windowsill today; dozens of beds outdoors later, without a
rewrite in between. Every design decision that looks over-engineered for three
plants is paying for that.

## Hard rules

These are not style preferences. Breaking one is a correctness bug.

1. **`RPi.GPIO` does not work on the Pi 5.** Its GPIO sits behind the RP1 south
   bridge. Use `gpiozero` with the `lgpio` pin factory. If you see `RPi.GPIO` in
   a dependency list or an import, it is wrong.

2. **`core/` is pure.** It imports nothing from `drivers`, `storage` or `web`,
   and performs no I/O — no files, no sockets, no database, no clock reads
   beyond what is passed in. This is what makes the whole decision path testable
   on a laptop in 30 milliseconds. (ARCH-4)

3. **Guards only ever subtract.** A safety guard may veto an actuation or
   shorten it. Nothing may lengthen or create one. (SAFE-1)

4. **Rules bind to roles, never to field names.** A rule asks for
   `ChannelRole.SOIL_MOISTURE` in a zone. It must never know which driver,
   which I2C address, or which multiplexer channel produced it. (DATA-3)

5. **Measurements are rows, not columns.** One row per
   `(channel, timestamp, value)`. Adding a sensor must never require a
   migration. If you find yourself adding a column per measurement, stop. (DATA-1)

6. **Manual actions go through the same guards as automatic ones.** A "water
   now" button that bypasses the daily budget is a bug with a nice icon. UI
   actions are queued as `commands` rows and executed by the control loop. (ARCH-3)

7. **The control service has no third-party dependencies.** Everything it needs
   is in the standard library. Web and hardware libraries are opt-in extras.
   A failed dependency install must not be able to stop watering.

8. **All timestamps are UTC and timezone-aware.** Local time exists only at
   display and when evaluating a watering window. Naive datetimes are rejected
   at construction.

## The repository

Claude Code owns this repository: branch, commit, push, open the pull request,
wait for CI, merge to `main`, tag the layer. No human approves a merge.
`docs/git-workflow.md` is the full contract; three things from it matter enough
to repeat here.

**CI is the reviewer.** Four checks plus the tripwires are required on `main`.
Merge on green. Never on red, never with `--admin`, never by silencing a check.
A change to a check goes in its own pull request, never alongside the work that
check judges — that is the difference between fixing a wrong gate and moving a
gate that was right.

**Three kinds of change must be declared** in the pull request body, with a
reason on the same line: tuning (`TUNING-CHANGE:`), safety constants
(`SAFETY-CHANGE:`), the requirements themselves (`CONTRACT-CHANGE:`), and
removing tests (`TEST-REMOVAL:`). None of them is forbidden. All of them are
forbidden to do quietly. `scripts/diff_gate.py` enforces it.

**A read-only `code-reviewer` subagent** (`setup/claude/agents/`, runs on Haiku)
checks a diff against the hard rules above and these declaration tripwires — it
runs automatically whenever a diff or pull request is being reviewed, and on
demand via `/review`.

**"What I was unsure about" is not optional.** Every pull request has that
section. In a repository where pull requests merge themselves it is the only
place doubt has anywhere to go — what was guessed, what was assumed about the
physical world, what a person should look at. "Nothing" is a suspicious answer.

Run the whole gate locally before pushing:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
ruff check . && mypy && python3 scripts/gate.py
```

## Layout

```
config/          TOML: hardware topology, under git. Tuning lives in the DB.
docs/            architecture.html is the spec. Read it.
src/smartgarden/
  core/          pure logic — models, physics, units, errors
  config/        TOML loading and validation
  drivers/       (layer 3) sensor and actuator plugins
  storage/       (layer 2) migrations, repositories, rollups
  runtime/       (layer 4) control loop, guards, watchdog
  web/           (layer 5) FastAPI + PWA
tests/
```

## Build status

| Layer | Contents | State |
|---|---|---|
| 1 | Foundation — config, core models, physics | **done** |
| 2 | Storage — migrations, repositories, rollups, export | **done** |
| 3 | Drivers — BME680, VEML7700, Seesaw, TCA9548A, simulated | merged; `smartgarden doctor` not yet run against real hardware |
| 4 | Runtime — control loop, guards, watchdog, panic-off | not started |
| 5 | API — FastAPI, ingest, systemd units | not started |
| 6 | Interface — PWA, charts, health, decision log | not started |

**Between layers 3 and 4 there is a deliberate gate.** Once the drivers work,
run the sensors for several days with `automation_enabled = false` and derive
real thresholds from what the Seesaw actually reports in this soil. The
placeholder values in `config/plants.toml` are almost certainly wrong — a
Seesaw reads roughly 200 (open air) to 2000 (in water), and where "dry" sits
depends entirely on the soil mix and probe depth. Building the control layer
against guessed thresholds produces something that runs without working.

## Commands

```bash
# Tests — no dependencies needed
PYTHONPATH=src python3 -m unittest discover -s tests -t .

# Or with pytest, which collects the same TestCase classes
pytest

# Validate configuration and print what it describes
PYTHONPATH=src python3 -m smartgarden.cli config check

# Sanity-check the physics against a reading
PYTHONPATH=src python3 -m smartgarden.cli physics --temp 22.4 --rh 48 --lux 8200
```

Installed (`pip install -e ".[dev]"`), the CLI is just `smartgarden`.

On the Pi, add the hardware extra: `pip install -e ".[pi,web,dev]"`.

## Conventions

- Python 3.13. Modern typing (`X | None`, `StrEnum`, `slots=True` dataclasses).
- Frozen dataclasses that validate in `__post_init__`. An impossible object
  should be impossible to construct, not merely detected later.
- Comments explain *why*, never *what*. If a constant has a provenance or a
  known limitation, say so where it lives.
- Error messages name the file, the key and the fix. They are read at 3am by
  someone whose plants are dying.
- Tests use `unittest.TestCase` so the suite runs with zero dependencies;
  pytest collects them unchanged.
- No `print` in application code — use `logging`. The CLI is the exception.

## Hardware

- Raspberry Pi 5, 8 GB, Pi OS Trixie (Debian 13, Python 3.13), 256 GB NVMe
- BME680 — air temperature, humidity, pressure, gas (I2C, 0x76 or 0x77)
- VEML7700 — ambient light (I2C, 0x10)
- Adafruit STEMMA Seesaw — soil moisture and temperature (I2C, 0x36–0x39)
- No actuators yet. Simulated drivers stand in; swapping to `gpio_relay` in
  `config/devices.toml` is the whole change.

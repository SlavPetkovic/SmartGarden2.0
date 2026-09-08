# SmartGarden

Sensor-driven irrigation and lighting for a Raspberry Pi 5.

Reads soil moisture, light and air conditions; decides when to water and when to
supplement light; records every decision with its reasoning; and presents all of
it on a phone. Built to run three plants on a windowsill now and dozens of
garden beds later, without a rewrite in between.

**[docs/architecture.html](docs/architecture.html) is the specification.** It
carries the design, the diagrams, and 72 numbered requirements this code is
written against. Start there.

## Status

Layer 1 of 6 complete: configuration, core domain types, physics. The system
does not yet read a sensor or water anything — that is layers 3 and 4.

## Quick start

```bash
git clone <your-repo-url> smartgarden && cd smartgarden
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

smartgarden config check
```

On the Raspberry Pi, add the hardware and web extras:

```bash
pip install -e ".[pi,web,dev]"
```

Note that `RPi.GPIO` is deliberately absent: it does not work on the Pi 5, whose
GPIO sits behind the RP1 south bridge. This project uses `gpiozero` with the
`lgpio` pin factory.

## Tests

The suite has no dependencies:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

`pytest` collects the same tests and gives nicer output.

## Configuration

Hardware topology lives in `config/` as TOML under version control. Per-plant
tuning — thresholds, windows, light targets — lives in the database and is
edited from the dashboard without a restart.

| File | Contents |
|---|---|
| `config/app.toml` | Paths, intervals, retention, the automation master switch |
| `config/sensors.toml` | Nodes and the sensors attached to them |
| `config/devices.toml` | Zones and the outputs that serve them |
| `config/plants.toml` | Plants and their seed care profiles |

**Automation ships disabled.** The loop reads, stores and logs what it *would*
have done, but drives nothing. Leave it that way until thresholds are calibrated
from several days of real readings — the placeholder values in `plants.toml` are
almost certainly wrong for your soil.

## Licence

Proprietary. All rights reserved.

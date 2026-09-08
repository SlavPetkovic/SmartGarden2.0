# Autonomous build contract

This document tells Claude Code, running on the Pi, how to build SmartGarden
unattended — and where it must stop and wait for a person.

`CLAUDE.md` says *what the code must look like*. `docs/architecture.html` says
*what the system must do*, in 72 numbered requirements. This file says *how the
build proceeds and what counts as done*. All three bind. Where they disagree,
`docs/architecture.html` wins.

---

## 1. The sequence

The blueprint's §12 lists six layers in dependency order, 01 through 06. That
order is correct as a dependency graph but wrong as a build order, for one
reason: §06 and `config/plants.toml` both say automation must not be enabled
until several days of real readings have set the moisture thresholds. Layer 04
built before that soak is layer 04 built against invented numbers.

So layer 04 is split. Everything that *observes* is built early, because the
dashboard needs it. Everything that *acts* waits for the soak.

| Stage | Layers | Ends with | Needs a person? |
|---|---|---|---|
| **A** | 02 → 03 → 04a → 05 → 06 | A dashboard showing live readings from the real sensors | Only for wiring |
| **B** | — | Seven or more days of logged data; calibrated thresholds | Yes — the thresholds are a judgement call |
| **C** | 04b | Rules, guards, watchdog, panic-off; automation enabled | Yes — every step |

Stage A is the answer to "I want to see a dashboard with readouts." It contains
no code that can turn anything on. Nothing in stage A can water a plant, because
nothing in stage A knows how.

---

## 2. The operating contract

Autonomous runs work on a branch named `auto/layer-NN`. They may:

- create and edit files under `src/`, `tests/`, `migrations/`, `web/`, `scripts/`
- edit `config/sensors.toml` **only** to correct an I2C address or mux channel
  that `smartgarden doctor` proved wrong, and must say so in the commit message
- run the test suite, `ruff`, `mypy`, and the `smartgarden` CLI
- install packages into `.venv` from the extras already declared in `pyproject.toml`
- commit to the work branch, as often as is useful
- **push the work branch, open a pull request, and merge it to `main` once every
  required check is green** — `docs/git-workflow.md` is the contract
- tag and release at a layer boundary
- edit `config/app.toml`, `config/plants.toml` or `config/devices.toml`, declaring
  the change with a `TUNING-CHANGE:` line in the pull request body that says what
  changed and what evidence says so

They may **not**, under any circumstance, without a person:

- merge on a red or pending check, with `--admin`, or by silencing or re-running
  a check until it flakes green
- force-push `main`, rewrite its history, or delete it
- change a check in `.github/workflows/` or `scripts/gate.py` in the same pull
  request as the work that check judges
- run `sudo`, or `systemctl start|stop|restart|enable|disable`
- set `automation_enabled = true`, propose setting it, or write code whose
  effect is to bypass it
- change a `simulated` driver to a real one
- weaken, skip, or `@expectedFailure` a test in order to pass a gate
- widen a plausible range, a `max_on_seconds`, or a budget to make something pass

The permission rules in `.claude/settings.json` enforce most of this
mechanically. The list above is the intent, and holds where a rule has a gap.

---

## 3. Hardware reality

Not every sensor is wired yet. `smartgarden doctor` (SENS-8) is the source of
truth about what is physically present, not `config/sensors.toml`, which
describes the intended topology.

Rules for a partly-populated bus:

- A configured sensor that does not answer is **reported absent, not an error**.
  The loop starts, the other sensors read, and the absent one shows as offline
  in the health view. This is DATA-4 behaving correctly.
- Driver tests run against the simulated drivers, always. Hardware-dependent
  tests are marked `@pytest.mark.hardware` (the marker is already declared in
  `pyproject.toml`) and are skipped when the device does not answer.
- Do not delete or comment out a `[[sensor]]` block because the hardware is not
  there yet. Absent is a valid state.
- If a sensor that *should* be present never answers, that is a stop condition —
  see §6. It is a loose STEMMA cable or a wrong address, and no amount of code
  fixes it.

---

## 4. The gate

A layer is done when every item in its gate is true. The gate is checked by
`scripts/autobuild.sh`; do not declare a layer complete without running it.

Every layer, without exception:

```
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t .   # green
.venv/bin/ruff check .                                              # clean
.venv/bin/mypy                                                      # clean, strict
```

`mypy` is configured `strict = true`. Clean means zero errors, not zero after
adding `# type: ignore`.

### Layer 02 — Storage · DATA-1…6, STOR-1…6

- Numbered SQL migration files applied in order, recorded in `schema_migrations`.
  One source of schema truth (STOR-1). A test applies them to a fresh database,
  then applies them again and asserts nothing changed.
- `readings` is narrow: one row per `(channel_id, ts, value, quality)` (DATA-1).
  A test asserts no column in `readings` is named after a measurement.
- `channel` rows are reconciled at startup from each driver's `channels()`
  declaration (DATA-2), including role, unit, precision and plausible range.
- Rollup job is idempotent (STOR-2) — a test runs it twice over one window and
  asserts identical output — and stores min, max, mean and count (STOR-3).
- `VACUUM INTO` backup with retention count, and a restore path that a test
  actually exercises (STOR-4).
- Export produces joined CSV: readings, decisions, actuations, outcomes (STOR-5).
- Every stored timestamp is UTC and timezone-aware. Constructing a reading from
  a naive datetime raises (STOR-6, and the hard rule in `CLAUDE.md`).
- SQLite opens WAL with an explicit `busy_timeout` (ARCH-5).

### Layer 03 — Drivers · SENS-1…8, SAFE-2

- A driver implements `channels()` and `read()` and registers itself by name.
  **Nothing else in the codebase enumerates driver types** (SENS-1). A test
  asserts the registry is discovered, not hand-listed.
- Implemented: `bme680`, `veml7700`, `seesaw_soil`, `tca9548a` mux support,
  plus simulated sensors and simulated actuators.
- A failed read retries with backoff, then records a failure against that
  sensor. One dead sensor does not stall the loop (SENS-2) — test with a driver
  that always raises, and assert the other sensors still produced readings.
- Out-of-range values are stored flagged, not dropped and not trusted (SENS-3).
- VEML7700 gain and integration time are set explicitly and recorded with the
  reading (SENS-5). A lux value whose gain is unknown is worthless.
- BME680 gas resistance is read and stored, and used by nothing (SENS-6).
- Simulated soil drying is a function of VPD and light, not random walk (SENS-7).
- `max_on_seconds` is enforced **inside** the actuator driver, whatever the
  caller asks for (SAFE-2). A test calls with 60 s against a 10 s device and
  asserts 10.
- `smartgarden doctor` scans the bus, walks mux channels, and reports per
  configured sensor: answered / did not answer / wrong address found (SENS-8).
- **Run `smartgarden doctor` on the Pi and put its output in the commit message.**

### Layer 04a — Observe-only runtime

This is the sensing half of the control service. It reads, stores, and reasons
out loud. It has no actuation path at all.

- Polls each sensor at its own `interval_seconds`, normalises, stores.
- Computes VPD from temperature and humidity every tick and stores it as a
  first-class derived channel (CTRL-10, ML-1) — not recomputed later.
- Writes a `decisions` row every tick with inputs, the action it *would* have
  chosen, and a reason string legible without reading source (CTRL-8).
- Marks a node offline when it has no reading inside `stale_after_seconds`
  (DATA-4).
- **A test asserts that with `automation_enabled = false` no actuator method is
  reachable from the loop.** Prove it by making the simulated actuator raise if
  called, then running a full tick cycle.
- Runs in the foreground as `smartgarden run`. Do not write or install systemd
  units here; they belong to layer 05.

### Layer 05 — API · ARCH-1…3, ARCH-6, API-1…4, OPS-1…3

- FastAPI, JSON only. No HTML templated from application state (API-1).
- Channel and role metadata served from an endpoint, so a new sensor appears in
  the UI with no front-end change (API-2).
- Time-series endpoints pick the rollup tier from the requested range (API-3).
  A test asserts a 1-hour range hits raw and a 60-day range hits quarter-hour.
- Ingest endpoint accepts external readings in the same normalised shape the
  local bus produces (ARCH-6).
- Token auth implemented, disabled by default, enabled by one config value
  (API-4).
- Manual actions arrive as `commands` rows and are drained by the loop — the web
  process never touches GPIO or I2C (ARCH-2, ARCH-3).
- Two systemd unit files are **written to `deploy/`** with restart-on-failure,
  journald logging and `ExecStopPost` (OPS-1). They are not installed, enabled
  or started; that is a person's job.
- Config validation fails loudly at startup with the file, the key and the fix
  (OPS-3). No `print` anywhere in application code (OPS-2).

### Layer 06 — Interface · UI-1…6

`docs/dashboard.html` is the design. Colours, type scale, spacing and layout are
already decided there — match it rather than inventing a second visual language.
It is a static mock with no data binding; the job is to make it real.

- Mobile-first, installable PWA: manifest, icons, service worker caching the
  shell (UI-1).
- Last known readings stay visible when the network drops, **marked with their
  age** rather than shown as current (UI-2).
- Thresholds, windows, budgets and DLI targets editable from the UI, taking
  effect without a restart (UI-3). These write to the database, never to
  `config/plants.toml`.
- Manual water and light buttons, labelled as still subject to safety guards,
  queueing `commands` rows (UI-4).
- Temperature unit is a display toggle; storage and computation stay SI (UI-5).
- Charts mark irrigation events on the time axis (UI-6).
- Four views: plant cards, history charts, system health, decision log.

**Stage A ends here.** The dashboard shows live readings from whatever is
actually wired, the decision log explains what the system would have done, and
nothing can act.

### Stage B — Soak. Not a build step.

Seven days minimum with `automation_enabled = false`, water each plant the way
you normally would, then read the chart. The plateau after watering is
`moisture_high`; the level where the plant starts to look thirsty is
`moisture_low`. `scripts/soak-report.sh` mails a nightly summary.

Claude does not set these numbers. Claude may summarise the data, plot it, point
at the plateaus, and say what it would pick — but a person edits
`config/plants.toml`, because getting this wrong is how a system runs without
working.

### Layer 04b — Control · CTRL-1…9, SAFE-1…8, OPS-4…6

Only after stage B. Even then, autonomous work stops at "written and tested with
simulated actuators."

- Guards are pure functions that only veto or shorten. **A property test
  generates random guard inputs and asserts no output ever exceeds its input
  duration** (SAFE-1). This is the single most important test in the codebase.
- Hysteresis band, not a single threshold (CTRL-1). Settling window after a
  pulse during which moisture is recorded but no new decision is made (CTRL-3).
- DLI accumulated per plant, reset at local midnight; supplement only within the
  photoperiod and only against a projected shortfall (CTRL-4, CTRL-5). Minimum
  dwell so cloud cannot chatter the relay (CTRL-7).
- Watchdog thread independent of the loop forces off anything past its limit
  (SAFE-3). A test kills the loop thread and asserts the watchdog still fires.
- `panic_off.py` is standalone and imports nothing from the application
  (SAFE-4). A test runs it as a subprocess with the package uninstallable.
- Outputs asserted off at startup before the first decision (SAFE-5).
- Daily budget and hourly cap evaluated in the zone's local timezone. **A test
  crosses a DST boundary** (SAFE-6).
- Global pause stops automation and manual commands while continuing to record
  (SAFE-7).
- Every actuation records pre-state, commanded duration, actual duration, and
  post-state after settling (CTRL-9, ML-3).
- Notifiers pluggable, alerts debounced and rate-limited (OPS-4…6).

Reserved for a person, always: enabling automation, swapping a driver from
`simulated` to `gpio_relay`, wiring the relay board, and the first live
actuation — which is watched, with a finger near the plug.

---

## 5. How to run it

Interactive, one layer at a time:

```bash
cd ~/SmartGarden
claude
> /next-layer 02
```

Unattended:

```bash
scripts/autobuild.sh 02        # builds, tests, iterates until the gate passes
scripts/autobuild.sh 03
```

The runner creates `auto/layer-NN`, invokes Claude with the gate for that layer,
re-checks the gate itself afterwards, and feeds failures back for another
attempt. It stops after six attempts and writes `.autobuild/BLOCKED-NN.md`.

On a green gate the runner pushes the branch and opens a pull request. CI
re-runs the same checks on a clean machine — which is the point, since a gate
that has only ever run on the Pi has only ever been checked against the Pi —
and the pull request merges itself on green. Pass `--no-ship` to stop after the
push if you want to read the diff first.

`docs/git-workflow.md` is the full contract for what a run may do to this
repository.

---

## 6. Stop conditions

Stop, write `.autobuild/BLOCKED-NN.md` explaining the situation, and wait:

1. The same gate check fails three attempts running with no progress between
   them. Repeating an approach that is not working is not persistence.
2. `smartgarden doctor` reports a sensor absent that should be wired. Hardware.
3. Passing the gate would require changing a requirement, a safety constant, a
   threshold, or a test's intent.
4. A denied action turns out to be genuinely necessary — say which, and why.
5. Anything about the physical world is ambiguous: which pin, which address,
   which plant, how wet is wet.

A blocked layer is a good outcome. A layer that passed because the test was
loosened is not.

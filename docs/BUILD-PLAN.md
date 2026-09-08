# SmartGarden — build plan

**This is the entry point.** Start here, from an empty `src/` and `tests/`.

Rev B · September 2026 · supersedes `PHASE1_PLAN.md`, `docs/autonomous-build.md`
and `docs/realign.md`, all of which should be deleted.

---

## 0. What binds, and in what order

Three documents. Read all three before writing any code.

| Document | Says | Authority |
|---|---|---|
| `docs/architecture.html` | **What the system must do** — 72 numbered requirements | Highest. Wins every disagreement. |
| `CLAUDE.md` | **What the code must look like** — 8 hard rules, conventions | Binding. A broken hard rule is a correctness bug, not a style miss. |
| this file | **How the build proceeds and what counts as done** | Binding on sequence, gates and autonomy. |

Requirement IDs (`SAFE-1`, `DATA-3`, `CTRL-10`) refer to `architecture.html`. Every
commit message names the IDs it satisfied. If a gate here seems to conflict with a
requirement there, the requirement is right and this file has a bug — say so and stop.

**Two previous attempts exist. Neither is a reference.**

- `github.com/SlavPetkovic/smartgarden` — the original. One column per measurement,
  `RPi.GPIO`, thresholds in `.env`. Superseded by design, not by accident.
- A prototype on the Pi at port 8000 (v0.2.0) — built from a different brief. Rules
  bound to driver field names, one process, tuning in a TOML file, invented moisture
  thresholds.

Do not read either for structure. §4 lists the four facts worth taking from them;
everything else about both is a decision that was reconsidered.

---

## 1. The three phases

**Phase 1 — a complete rule-based system.** Reads three real sensors, stores
everything, decides when to water and light, acts through drivers, and presents all of
it on a phone. Irrigation hardware does not exist yet, so Phase 1 ships simulated
actuators alongside real sensor drivers; switching to relays is an edit to
`config/devices.toml`. This is the whole of the work described below.

**Phase 2 — moisture decay forecasting.** Predict time-to-stress from current
moisture, VPD, light and soil temperature, instead of extrapolating a line through the
last two readings. Requires several weeks of logged data across varied conditions.
Nothing in Phase 1 implements it; Phase 1's job is to produce data of the right shape,
because that cannot be backfilled. See §7.

**Phase 3 — reach.** Native mobile app, remote wireless nodes in outdoor beds, camera
and plant imagery. The JSON API and the ingest endpoint are the seams; both are built
in Phase 1, neither is exercised by a second consumer yet. See §8.

Phase 1 is the only phase with a build plan, and that is deliberate. Phase 2's design
depends on what the data actually looks like, and specifying it now would be fiction
dressed as a requirement.

---

## 2. Phase 1 at a glance

Six layers, dependencies running strictly downward, with a soak in the middle that is
not a build step.

| Stage | Layers | Ends with | Person needed? |
|---|---|---|---|
| **A** | 01 → 02 → 03 → 04a → 05 → 06 | Dashboard showing live readings from real sensors. **Nothing can act.** | Only to wire the Seesaw |
| **B** | — | ≥7 days of logged readings; calibrated moisture thresholds | Yes — the thresholds are a judgement call |
| **C** | 04b | Rules, guards, watchdog, panic-off; automation enabled | Yes — every step |

Layer 04 is split for one reason: `architecture.html` §06 and `config/plants.toml` both
say automation must not be enabled until days of real readings have set the moisture
thresholds. Layer 04 built before the soak is layer 04 built against invented numbers.
So everything that *observes* is built early, because the dashboard needs it, and
everything that *acts* waits.

Nothing in stage A can water a plant, because nothing in stage A knows how.

**Layers 01–03 run on a laptop.** Only `doctor` and layer 04a onward want the Pi.

**Wire the Seesaw now, during layers 01–03.** The soak is the long pole of the entire
project and its clock cannot start until that sensor reports real counts from real soil.

---

## 3. Autonomy — what a run may and may not do

Autonomous runs work on a branch named `auto/layer-NN`. They may:

- create and edit files under `src/`, `tests/`, `migrations/`, `web/`, `scripts/`, `deploy/`
- edit `config/sensors.toml` **only** to correct an I2C address or mux channel that
  `smartgarden doctor` proved wrong, saying so in the commit message
- run the test suite, `ruff`, `mypy`, `scripts/gate.py`, and the `smartgarden` CLI
- install packages into `.venv` from extras already declared in `pyproject.toml`
- commit to the work branch, as often as is useful
- **push the work branch, open a pull request, and merge it to `main` once every
  required check is green** — see `docs/git-workflow.md`
- tag and release at a layer boundary
- edit `config/app.toml`, `config/plants.toml` or `config/devices.toml`, declaring
  the change with a `TUNING-CHANGE:` line in the pull request body

They may **not**, under any circumstance, without a person:

- merge on a red or pending check, with `--admin`, or by disabling or re-running a
  check until it flakes green
- force-push `main`, rewrite its history, or delete it
- change a check in `.github/workflows/` or `scripts/gate.py` **in the same pull
  request as the work that check judges** — a gate change goes in its own pull request
- run `sudo`, or `systemctl start|stop|restart|enable|disable`
- set `automation_enabled = true`, propose setting it, or write code whose effect is to
  bypass it — and creating `.stage-b-complete`, which is what would permit it, is a
  person's act, not a run's
- change a `simulated` driver to a real one
- weaken, skip or `@expectedFailure` a test to pass a gate
- widen a plausible range, a `max_on_seconds` or a budget to make something pass

**On the three config files.** They used to be un-editable by a run, because they hold
`automation_enabled`, the moisture thresholds and the driver selection — the three
things standing between a simulation and water on the floor. They are now editable and
*declarable*: `scripts/diff_gate.py` fails any pull request that touches one without a
`TUNING-CHANGE:` line saying what changed and what evidence says so. The point was
never to make the edit hard. It was to make it impossible to make quietly, because the
previous attempt shipped `moisture < 30%`, a 5 s pulse and a 180 s daily cap, and every
one of those numbers was invented. If the honest reason for a tuning change is "I needed
a number and did not have one", that is not a token — that is the soak gate, and the
answer is to stop.

`.claude/settings.json` enforces most of this mechanically, and CI enforces the rest.
The list above is the intent, and holds where a rule has a gap.

**Stop conditions.** Stop, write `.autobuild/BLOCKED-NN.md`, and wait when:

1. The same gate check fails three attempts running with no progress between them.
   Repeating an approach that is not working is not persistence.
2. `smartgarden doctor` reports absent a sensor that should be wired. That is hardware.
3. Passing the gate would require changing a requirement, a safety constant, a
   threshold, or a test's intent.
4. A denied action turns out to be genuinely necessary — say which, and why.
5. Anything about the physical world is ambiguous: which pin, which address, which
   plant, how wet is wet.

A blocked layer is a good outcome. A layer that passed because a test was loosened
is not.

---

## 4. Hardware — the facts, and the one trap

Confirmed from the original repository's `pi_reader.py` and `pi_actuator.py`.

**The I2C bus.** All three sensors share bus 1 — `board.I2C()`, GPIO2 (SDA, header pin
3) and GPIO3 (SCL, header pin 5), with 3V3 on pin 1 and GND on pin 6.

| Device | Address | Provides | Status |
|---|---|---|---|
| BME680 | `0x77` (some breakouts `0x76`) | air temp, humidity, pressure, gas resistance | wired |
| VEML7700 | `0x10` | ambient lux | wired |
| Seesaw STEMMA soil | `0x36` (default, no jumpers bridged) | capacitance counts, soil temp | **to be wired** |

The Seesaw is not on a dedicated pin. It joins the same bus. If the SmartGarden HAT is
populated, it plugs straight into that board's 4-pin JST-PH `moisture sensor` connector
— see `docs/hardware/board.md`; otherwise it is four wires onto the header, or a STEMMA
daisy-chain. `0x36`–`0x39` are the only four addresses available, which is why TCA9548A
multiplexer support is in the driver layer from the start (SENS-4).

`i2cdetect -y 1` is the truth about what is present. `config/sensors.toml` describes
the *intended* topology. A configured sensor that does not answer is **reported absent,
not an error** — the loop starts, the others read, the absent one shows offline in the
health view. That is DATA-4 behaving correctly. Do not delete or comment out a
`[[sensor]]` block because the hardware is not there yet.

**Relay pins, for `config/devices.toml` when relays arrive:** grow light **GPIO24**
(pin 18), pump **GPIO23** (pin 16), `active_low = true`. These are not carried over on
trust — they were traced out of the recovered board Gerbers and independently agree
with the original firmware. The full netlist, connector pinouts and wiring cautions are
in `docs/hardware/board.md`; the fabrication files are in `docs/hardware/gerbers/`.

**The trap.** The original drove those pins with `import RPi.GPIO as GPIO`. On the Pi 5
that library cannot address the GPIO at all — it moved behind the RP1 south bridge. The
pin numbers carry over; the library does not. All GPIO goes through `gpiozero` with the
`lgpio` pin factory (PLAT-2), and `RPi.GPIO` must not appear anywhere in the dependency
tree. Check with `pip list | grep -i rpi` and `pipdeptree`, not by inspection —
`--no-deps` installs are exactly how it sneaks in.

**Install note.** On Trixie, `adafruit-blinka` pulls `lgpio`, which wants swig and
sudo. The workaround that worked: install `adafruit-lgpio` and use `--no-deps`. Record
whatever you end up doing in `docs/pi-setup.md`, and then run the `RPi.GPIO` check
above, because that flag is how PLAT-2 gets violated silently.

**Observed indoor ranges**, for setting plausible ranges honestly rather than inventing
bounds: gas resistance ~200 kΩ, pressure ~979 hPa, air temperature ~27 °C, lux from ~70
at night to daylight peak. Soil is unknown until the Seesaw is wired — that is the
point of the soak.

**What the previous systems used, so you recognise it and do not copy it:** a stress
threshold of `350`, a lux threshold of `100`, a 3 s pump pulse, a 300 s cooldown. The
Seesaw reads roughly 200 in open air and 2000 in water; `350` is nearly "probe in air".
These are the numbers the soak exists to replace.

---

## 5. Phase 1 — the layers

Every layer, without exception, ends green on all three:

```
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t .   # green
.venv/bin/ruff check .                                              # clean
.venv/bin/mypy                                                      # clean, strict
```

`mypy` is configured `strict = true`. Clean means zero errors, not zero after adding
`# type: ignore`.

Tests use `unittest.TestCase` so the suite runs with zero dependencies; pytest collects
them unchanged. Hardware-dependent tests are marked `@pytest.mark.hardware` and skip
when the device does not answer. Driver tests run against simulated drivers, always.

---

### Layer 01 — Foundation · PLAT-1…4, ARCH-4, CTRL-10

The skeleton and the pure core. No I/O anywhere in it.

- `pyproject.toml` declaring dependencies once, with a lock file generated and **no
  hand-maintained `requirements.txt`** (PLAT-3). Hardware libraries are an optional
  `[pi]` extra so the suite installs and runs on a laptop (PLAT-4). Python 3.13,
  project-local `.venv`, nothing in system Python (PLAT-1).
- `src/smartgarden/core/` — frozen, slotted dataclasses validating in `__post_init__`.
  An impossible object must be impossible to construct, not merely detected later.
- Physics: VPD, dew point, DLI accumulation, lux→PPFD, unit conversion. All pure
  functions, all tested against worked values with the source of each constant named
  in a comment where it lives.
- `config/` loading and validation for `app.toml`, `sensors.toml`, `devices.toml`,
  `plants.toml`. Errors name the file, the key and the fix — they are read at 3am by
  someone whose plants are dying (OPS-3).
- `docs/architecture.html` and this file committed to `docs/`.
- A `smartgarden` CLI entry point with `config check` and `physics` subcommands.

**Gate:**

- `core/` imports nothing from `drivers`, `storage` or `web`, and performs no I/O — no
  files, no sockets, no database, no clock reads beyond what is passed in (ARCH-4).
  **A test asserts this by inspecting the import graph**, not by reading the code.
- Constructing any timestamped object from a naive datetime raises (STOR-6).
- VPD, dew point and DLI each carry tests with hand-computed expected values.
- `RPi.GPIO` appears nowhere in the dependency tree (PLAT-2).
- `smartgarden config check` validates the four TOMLs and prints what they describe.

---

### Layer 02 — Storage · DATA-1…6, STOR-1…6, ARCH-5

Narrow rows, tiered retention, and one source of schema truth.

- Numbered SQL migration files applied in order and recorded in `schema_migrations`
  (STOR-1). **A test applies them to a fresh database, then applies them again and
  asserts nothing changed.**
- Tables per the blueprint's §04 entity model: `node`, `sensor`, `channel`, `reading`,
  `zone`, `plant`, `device`. The `role` column on `channel` is load-bearing.
- `readings` is narrow — one row per `(channel_id, ts, value, quality)` (DATA-1).
  **A test asserts no column in `readings` is named after a measurement.**
- `channel` rows reconciled at startup from each driver's `channels()` declaration —
  key, unit, precision, plausible range, role (DATA-2).
- Every node carries `stale_after_s` (DATA-4). Readings carry a quality flag so a
  retried or out-of-range sample is recorded rather than discarded (DATA-6).
- Rollup job: raw 10 s/60 s kept 7 days, minute kept 90 days, quarter-hour kept
  indefinitely. Idempotent (STOR-2) — **a test runs it twice over one window and
  asserts identical output** — storing min, max, mean and count, not just mean (STOR-3).
- `VACUUM INTO` backup with a retention count, and a restore path **a test actually
  exercises** (STOR-4).
- Export producing joined CSV — readings, decisions, actuations, outcomes (STOR-5).
- SQLite opens WAL with an explicit `busy_timeout`, so a long analytics read cannot
  fail a control-loop write (ARCH-5).
- All timestamps UTC, ISO-8601, timezone-aware (STOR-6).

---

### Layer 03 — Drivers · SENS-1…8, SAFE-2

Plugins. Failure is expected and recorded rather than thrown away.

- A driver implements `channels()` and `read()` and registers itself by name.
  **Nothing else in the codebase enumerates driver types** (SENS-1) — a test asserts
  the registry is discovered, not hand-listed.
- Implemented: `bme680`, `veml7700`, `seesaw_soil`, `tca9548a` mux support, plus
  simulated sensors and simulated actuators.
- A failed read retries with backoff, then records a failure against that sensor. One
  dead sensor must not stall the loop (SENS-2) — **test with a driver that always
  raises, and assert the other sensors still produced readings.**
- Out-of-range values are stored flagged, not dropped and not trusted (SENS-3).
- VEML7700 gain and integration time set explicitly and recorded with the reading
  (SENS-5). A lux value whose gain is unknown is worthless.
- BME680 gas resistance read and stored, used by nothing — it needs burn-in and is
  calibrated to nothing meaningful (SENS-6).
- Simulated soil drying is a function of VPD and light, not a random walk (SENS-7).
  **The simulated Seesaw emits capacitance counts in the 200–2000 range, not a
  percentage** — a mock that emits a unit the real sensor does not emit hides the
  conversion bug instead of surfacing it.
- `max_on_seconds` enforced **inside the actuator driver**, whatever the caller asks
  (SAFE-2). **A test calls with 60 s against a 10 s device and asserts 10.**
- `smartgarden doctor` scans the bus, walks mux channels, and reports per configured
  sensor: answered / did not answer / wrong address found (SENS-8).
- **Run `smartgarden doctor` on the Pi and put its output in the commit message.**

---

### Layer 04a — Observe-only runtime · CTRL-8, CTRL-10, DATA-4, ML-1

The sensing half of the control service. It reads, stores, and reasons out loud. It
has no actuation path at all.

- Polls each sensor at its own `interval_seconds` — **per channel, not one global
  rate.** Light and air move quickly and are read every 10 s; soil moves slowly and is
  read every 60.
- Computes VPD from temperature and humidity every tick and stores it as a
  first-class derived channel (CTRL-10, ML-1) — not recomputed later from
  possibly-rolled-up inputs.
- Writes a `decisions` row every tick: inputs considered, the action it *would* have
  chosen, and a reason string legible without reading source (CTRL-8).
- Marks a node offline when it has no reading inside `stale_after_seconds` (DATA-4).
- Runs in the foreground as `smartgarden run`. **Do not write or install systemd units
  here** — they belong to layer 05.

**Gate, and it is the important one:** a test asserts that with
`automation_enabled = false` **no actuator method is reachable from the loop**. Prove
it by making the simulated actuator raise if called, then running a full tick cycle.

---

### Layer 05 — API · ARCH-1…3, ARCH-6, API-1…4, OPS-1…3

- FastAPI, **JSON only**. No HTML templated from application state; the PWA is served
  as static assets (API-1).
- Channel and role metadata served from an endpoint, so a new sensor appears in the UI
  with no front-end change (API-2).
- Time-series endpoints pick the rollup tier from the requested range (API-3). **A test
  asserts a 1-hour range hits raw and a 60-day range hits quarter-hour.**
- Ingest endpoint accepts external readings in the same normalised shape the local bus
  produces, so a remote node is indistinguishable downstream (ARCH-6). **A test posts a
  reading under a second node id and asserts it lands in the same tables, resolves the
  same roles and reaches the same time-series endpoints as one from the local bus.**
  With only one node in existence, ARCH-6 is easy to build subtly wrong and impossible
  to notice; that test is the only thing standing in for the second node until it
  arrives. See §7 — the node hardware is now chosen.
- Token auth implemented, **disabled by default**, enabled by one config value (API-4).
- Manual actions arrive as `commands` rows and are drained by the loop. **The web
  process never touches GPIO or I2C** (ARCH-2, ARCH-3). A "water now" button that
  bypasses the daily budget is a bug with a nice icon.
- **Two** systemd unit files written to `deploy/` — control and web, independent, with
  restart-on-failure, journald logging and `ExecStopPost` on the control unit (OPS-1,
  ARCH-1). They are not installed, enabled or started; that is a person's job.
- No `print` anywhere in application code; structured `logging` throughout (OPS-2).

The two-process split is not architectural taste. A crash in the dashboard, or a deploy
of a UI change, must never interrupt watering. They communicate only through SQLite:
the loop writes observations and drains the command queue, the web process writes
commands and settings and reads everything else. **Neither process imports the other.**

---

### Layer 06 — Interface · UI-1…6

`docs/dashboard.html` is the design. Colours, type scale, spacing and layout are
decided there — match it rather than inventing a second visual language. It is a static
mock with no data binding; the job is to make it real.

- Mobile-first, installable PWA: manifest, icons, service worker caching the shell
  (UI-1).
- Last known readings stay visible when the network drops, **marked with their age**
  rather than shown as current (UI-2).
- Thresholds, windows, budgets and DLI targets editable from the UI, taking effect
  without a restart (UI-3). **These write to the database, never to
  `config/plants.toml`.** Tuning lives in SQLite and is changed from a phone; hardware
  topology lives in TOML under git and is changed by an editor and a commit.
- Manual water and light buttons, labelled as still subject to safety guards, queueing
  `commands` rows (UI-4).
- Temperature unit is a display toggle; storage and computation stay SI (UI-5).
- Charts mark irrigation events on the time axis, so cause and effect read in one
  glance (UI-6).
- Four views: plant cards ("is anything thirsty?"), history charts ("did watering
  change it?"), system health ("is anything offline?"), decision log ("why did it not
  water?").

**Every rule and every UI element references a channel by its role in a zone —
`soil_moisture`, `air_temp`, `light` — never by driver, field name, I2C address or mux
channel** (DATA-3, SCOPE-3). This is the primary design constraint of the project. It
is what lets you replace a sensor, move it to another mux channel, or add a twentieth
plant without touching a rule. Both previous attempts failed here first.

**Stage A ends.** The dashboard shows live readings from whatever is actually wired,
the decision log explains what the system would have done, and nothing can act.

---

### Stage B — the soak. Not a build step.

Seven days minimum with `automation_enabled = false`. Water each plant the way you
normally would. Then read the chart: the plateau after watering is `moisture_high`; the
level where the plant starts to look thirsty is `moisture_low`.
`scripts/soak-report.sh` writes a nightly summary.

Claude does not set these numbers. Claude may summarise the data, plot it, point at the
plateaus and say what it would pick — but **a person edits `config/plants.toml`**,
because getting this wrong is how a system runs without working.

---

### Layer 04b — Control · CTRL-1…9, SAFE-1…8, OPS-4…6

Only after stage B. Even then, autonomous work stops at "written and tested with
simulated actuators."

- **Guards are pure functions that only veto or shorten. A property test generates
  random guard inputs and asserts no output ever exceeds its input duration** (SAFE-1).
  This is the single most important test in the codebase. Nothing may lengthen or
  create an actuation.
- Irrigation on a hysteresis band, not a single threshold — a single threshold
  oscillates (CTRL-1). Fixed per-zone pulse duration in Phase 1 (CTRL-2). Settling
  window after a pulse during which moisture is recorded but no new decision is made
  (CTRL-3).
- Lighting by daily light integral, **not a lux threshold**: accumulate measured
  illuminance into mol·m⁻²·d⁻¹ per plant, reset at local midnight, supplement only
  within the photoperiod and only against a projected end-of-day shortfall (CTRL-4,
  CTRL-5). The lux→PPFD factor is configurable per fixture with its assumption
  documented, since it is spectrum-dependent and approximate (CTRL-6). Minimum dwell so
  a passing cloud cannot chatter the relay (CTRL-7).
- Watchdog thread independent of the control loop forces off anything past its limit
  (SAFE-3). **A test kills the loop thread and asserts the watchdog still fires.**
- `panic_off.py` standalone, importing nothing from the application, run from
  `ExecStopPost` (SAFE-4). **A test runs it as a subprocess with the package
  uninstallable.**
- Outputs initialise off at startup and are asserted off before the first decision
  (SAFE-5).
- Per-zone daily water budget and per-hour pulse cap, evaluated in the zone's local
  timezone. **A test crosses a DST boundary** (SAFE-6).
- Global pause stops all automation and manual commands while continuing to record
  (SAFE-7).
- Relay polarity configurable per device, defaulting to the safe interpretation, and
  verified by `doctor` before automation is enabled (SAFE-8).
- Every actuation records pre-state, commanded duration, actual duration, and
  post-state after settling (CTRL-9, ML-3).
- Notifiers pluggable; alerts debounced and rate-limited per condition (OPS-4…6). An
  alerting system that cries wolf gets muted, which is worse than none.

The three safety layers are independent by design: config guards, a driver-enforced
`max_on_seconds`, and a watchdog plus `ExecStopPost` that both reach the hardware
**without the control loop participating** — which is exactly the condition under which
a stuck valve happens.

**Reserved for a person, always:** enabling automation, swapping a driver from
`simulated` to `gpio_relay`, wiring the relay board, and the first live actuation —
watched, with a finger near the plug.

---

## 6. Running the build

```bash
cd ~/SmartGarden
claude
> /next-layer 01
```

Or unattended, one layer at a time:

```bash
scripts/autobuild.sh 01
```

The runner creates `auto/layer-NN`, invokes Claude with that layer's gate, re-checks
the gate itself afterwards, and feeds failures back for another attempt. It stops after
six attempts and writes `.autobuild/BLOCKED-NN.md`.

On a green gate it pushes the branch and opens a pull request. CI re-runs the same
checks on a clean machine — which is the point, because a gate that only ever ran on
the Pi has only ever been checked against the Pi — and the pull request merges itself
on green. `--no-ship` stops after the push if you want to read the diff first.

Order: `01 → 02 → 03 → 04a → 05 → 06`, then the soak, then `04b`.

`docs/git-workflow.md` is the full contract for what a run may do to this repository.

---

## 7. Phase 2 — moisture decay forecasting

**The goal.** Given current moisture, VPD, light and soil temperature, predict how many
hours until this plant hits its stress threshold. That replaces the straight line
through the last two readings that both previous attempts drew, which is wrong in
exactly the conditions that matter — a hot dry afternoon.

**Prerequisite: several weeks of logged data across varied conditions.** Not days. The
model needs to have seen a cold cloudy week and a hot bright one. Until then the rule
baseline *is* the system, and its decision log is the benchmark any model has to beat.

**What Phase 1 must produce, because none of it can be backfilled:**

- `ML-1` — VPD computed and stored on every tick as a first-class derived channel, not
  recomputed at fit time from rolled-up inputs.
- `ML-2` — irrigation events with explicit start and end boundaries plus a settling
  window, so drying segments between waterings extract unambiguously.
- `ML-3` — pre-state, commanded duration, actual duration and post-state per actuation.
  These are labelled examples for a dose–response model, if that direction is picked up.
- `ML-4` — the quality flag from DATA-6, so suspect samples are excludable at fit time
  without deleting them.
- `ML-5` — minute-resolution data retained 90 days. That is the training resolution and
  horizon a first model needs.
- `ML-6` — the decision table recording what the system believed at decision time, so a
  model can be evaluated against the rule baseline on identical history.

**Sequencing when it starts:** export via STOR-5 into a notebook, characterise drying
curves per plant, fit offline, evaluate against the logged rule decisions on the same
history, and only then consider putting a model in the loop — behind the same guards,
which do not change. A model proposes; the guards still only subtract.

## 7a. Remote nodes — hardware chosen, build deferred

**Decision, 2026-09-08.** Remote sensor nodes will be **Raspberry Pi Zero 2 W**. They
stay Phase 2: everything is built on the Pi 5 first, and the Zero arrives afterwards as
an additional node, never as a replacement.

**The real deployment, decided the same day.** Two zones, not one system in two places:

| Zone | Node | Carries |
|---|---|---|
| `indoor` | `pi-local` — the Pi 5, in the house | 1 Seesaw · 1 BME680 · 1 VEML7700 |
| `garden` | `bed-1` — a Zero 2 W at the bed | 10+ Seesaws behind a TCA9548A · 1 BME680 · 1 VEML7700 |

One outdoor bed, ten or more plants at 20–30 cm spacing. Each zone carries its **own**
air and light sensors, because indoor and outdoor weather are different measurements
rather than noisy copies of one — and VPD is derived per zone from that zone's own
temperature and humidity (CTRL-10), so a zone without an air sensor has no VPD at all.
The address ceiling is per bus, so the indoor Seesaw at `0x36` and a garden Seesaw at
`0x36` never collide.

This makes the node **mandatory rather than optional**: I²C will not reach from the
house to the bed, so without the node the garden is simply unmeasured. It does not
change when the node is built (see the sequencing decision below), but it does change
what it is — not a nice-to-have second data source, but the only path to the plants the
project actually exists for.

**Sequencing decision, 2026-09-08: finish Phase 1 indoors first.** All six layers, the
indoor soak, then automation, and only then the node. Every layer gets proven on a
machine that can be reached and reset before anything goes in the ground. The known
cost is seasonal — outdoor soil in September behaves differently from outdoor soil in
June, and ML-5 wants weeks across varied conditions, so the date the node arrives on
decides which season the first outdoor record describes. Accepted knowingly. Digging,
wiring and weatherproofing the bed has no software dependency and can proceed in
parallel.

This is the right order, and it is also the order the blueprint already assumed: the
ingest endpoint (ARCH-6) and the `node` entity exist in Phase 1 precisely so that a
board in a garden bed is the same kind of thing as the Pi's own bus. Sensors carry
`node = "pi-local"` today; a Zero's sensors are `[[sensor]]` blocks with
`node = "bed-1"` and nothing downstream changes. Rules bind to roles in zones (DATA-3),
so no rule, chart or decision-log entry knows whether a reading came over I²C or Wi-Fi.

**Nothing in Phase 1 needs to change for this.** Four things already in the gates are
what make the seam work, and they are worth building properly rather than treating as
box-ticking, because with one node they all look like no-ops:

- `node` rows are real from layer 02 — the schema must not quietly collapse to a single
  implicit node.
- `stale_after_s` per node and the offline logic (DATA-4). Nearly meaningless for a bus
  30 cm away; the whole safety story for a node on garden Wi-Fi.
- The layer 05 ingest test that posts under a second node id (§5, layer 05).
- The layer 06 health view reports **nodes**, not only sensors.

### Bus, mux or node — the general rule

**A node answers distance. A multiplexer answers everything after the fourth plant.**

| | You add | Because | Ceiling |
|---|---|---|---|
| 1 | One more Seesaw — a `[[sensor]]` block and a `[plant]` block | A free address remains on that bus | **4 plants.** `0x36`–`0x39` is every address a Seesaw has |
| 2 | A TCA9548A multiplexer | Addresses gone, plants still in reach | **32 per bus.** Still one bus, still one machine |
| 3 | A Zero 2 W node | Too far to wire — another room, outdoors | Many. Cheap once the first exists |

Only the third step buys a computer. Nothing in Phase 1 changes for any of them: the
multiplexer is already in the layer 03 gate (SENS-4, *"since Seesaw offers only four
addresses and the target is dozens of plants"*), and tiers 1 and 2 are config edits
against code that will already exist.

**The bed goes straight to tier 3 plus tier 2, and the mux there is not optional.**
Ten Seesaws on one bus fails twice over, independently of addresses:

- Every Seesaw carries a 10 kΩ pull-up on SDA and SCL. Ten in parallel is 1 kΩ, drawing
  roughly 2.9 mA at the 0.4 V logic-low threshold — at the 3 mA the I²C standard
  allows, before the host's own pull-ups are counted, which push it over.
- Ten sensors on ~1 m runs each is ~10 m of cable against a 400 pF bus-capacitance
  budget. Also over.

A TCA9548A connects **one branch at a time**, so both pull-up current and capacitance
become per-branch instead of cumulative: two sensors on a branch is 5 kΩ and ~2 m.
This is the less obvious half of what the multiplexer buys, and the half that decides
whether the bed works at all. Put the BME680 and VEML7700 on the node's main bus rather
than behind the mux — no address conflict with `0x70`, and they stay readable whatever
channel is selected.

**What makes growth cheaper than it looks.** BME680 and VEML7700 measure the
environment, not the plant — one of each per *zone*, and an extra plant in that zone
needs only a soil sensor. DLI accumulates per plant (CTRL-4), but plants inherit their
zone's light reading where their own is unset (DATA-5); a plant gets its own light
sensor only if it sits somewhere meaningfully shadier. Zones keep window, budget and
thresholds apart, so adding one never perturbs another.

**Ten plants is one soak, not ten.** Calibration describes a probe at a depth in a soil
mix — and ten plants in one bed share all three. Run the bed once with every probe
logging simultaneously and ten drying curves arrive in parallel; they will cluster. Set
the zone default from the cluster and override only the plants that genuinely differ,
which is precisely what DATA-5 means by inheriting zone defaults where unset. The
sensors are the cheap part; the seven days are the cost, and they are paid once per bed
rather than once per plant.

**When the node is built — the standing constraints.** Recorded now so they are not
rediscovered later:

1. **It runs the same `drivers/` code**, with a thin read-and-ship runtime in place of
   the control loop. One codebase, two entry points. A second sensor implementation on
   the node is exactly the failure SENS-1 exists to prevent.
2. **Clock.** A Zero has no RTC. Booted without network it believes it is 1970 and will
   emit timestamps that violate STOR-6 and poison the training set. Either refuse to
   send until NTP has synced, or send elapsed-time offsets and let ingest stamp arrival.
   The second is more robust.
3. **Link loss.** Garden Wi-Fi drops. Under SCOPE-4 the Phase 1 data *is* the Phase 2
   training set, so dropped samples are unbackfillable. Default to a small bounded
   store-and-forward buffer, replaying on reconnect, with replayed samples marked via
   the DATA-6 quality flag. Open decision, to be taken against real measured link
   quality at the bed rather than in advance.
4. **If a node ever actuates, its entire safety envelope must be local to it.**
   `max_on_seconds` in the driver (SAFE-2), the watchdog thread (SAFE-3) and panic-off
   (SAFE-4) cannot live on the Pi 5 across a Wi-Fi link — a valve opened by a remote
   command with a partition before the off command arrives is the stuck valve those
   requirements exist to prevent. Open decision; the node is sensors-only until it is
   taken deliberately.

**Practical.** The plain Zero 2 W ships with the 40-pin header **unpopulated** — order
the WH variant or solder one. Put it on the tailnet, which keeps API-4's token auth off
and consistent with the blueprint's access model. And note that "battery-powered board
in a garden bed", as §04 of `architecture.html` puts it, overstates a Zero 2 W: it has
no useful sleep state and keeps Wi-Fi up. Mains or solar-plus-battery is realistic;
months on cells is not, and would mean an ESP32-class node instead.

---

## 8. Phase 3 — reach

Sketch only. Nothing here constrains Phase 1 beyond keeping the seams honest.

- **Native mobile app.** The PWA covers most of it. The JSON API is the seam, which is
  why API-1 forbids templating HTML from application state — a second consumer must be
  able to exist.
- **Camera and plant imagery.** A separate dataset and a separate problem. No hooks
  built, deliberately.
- **Weather forecast integration.** The ingest layer is generic enough to accept it
  later as another data source. Deferred, not designed.
- **User accounts.** Tailscale is the access boundary. Token auth is implemented and
  disabled (API-4); if the service is ever exposed beyond the tailnet it is one config
  value, not a project.
- **Scale-out.** Three plants on a windowsill today, dozens of beds outdoors later,
  without a rewrite in between. Every Phase 1 decision that looks over-engineered for
  three plants — roles, zones, nodes, narrow rows, the multiplexer in the driver layer
  — is paying for that.

---

## 9. Starting from zero — what to say to Claude Code

Fresh session in `~/SmartGarden`, with `docs/architecture.html`, `CLAUDE.md`,
`docs/dashboard.html`, `config/*.toml` and this file present, and `src/` and `tests/`
empty:

> We are building SmartGarden from zero. `docs/BUILD-PLAN.md` is the entry point — read
> it first, then `docs/architecture.html` for the 72 requirements and `CLAUDE.md` for
> the hard rules. Where they disagree, `architecture.html` wins.
>
> Two earlier attempts exist — the GitHub repo and a prototype running on this Pi at
> port 8000. Neither is a reference for structure. §4 of the build plan lists the four
> hardware facts worth taking from them; do not read either for anything else.
>
> Three things to hold on to throughout, because both earlier attempts got each of them
> wrong and everything else rests on them:
>
> 1. A rule or UI element names a **role** in a zone, never a driver, a field name or
>    an I2C address (DATA-3, SCOPE-3).
> 2. Measurements are **rows, not columns** — adding a sensor must never require a
>    migration (DATA-1).
> 3. Nothing in stage A builds an actuation path at all. If a gate looks like it needs a
>    moisture threshold, that is the soak gate and the answer is to stop, not to guess.
>
> Start with `/next-layer 01`. Before you build, tell me in three lines what you are
> about to build and what its gate requires.

For every layer after 01, `/next-layer NN` carries its own gate and needs no further
briefing.

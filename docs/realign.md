# Realigning the Pi build to the blueprint

**Status:** what is running on the Pi at `192.168.1.71:8000` (v0.2.0) is not the
system `docs/architecture.html` describes. It is a working prototype of a
different design. This document says what to do about that.

Read with `docs/architecture.html` (the 72 requirements), `CLAUDE.md` (the hard
rules) and `docs/autonomous-build.md` (the layer gates). Where any of this
disagrees with the blueprint, the blueprint wins.

---

## 1. What happened

Two codebases now carry the name SmartGarden.

| | Blueprint repo (`OneDrive\PROJECTS\SmartGarden`) | Pi prototype (v0.2.0, running) |
|---|---|---|
| Built from | `docs/architecture.html`, 72 requirements | `PHASE1_PLAN.md`, a four-goal brief |
| Progress | Layer 01 done: `core/`, `config/`, physics, 5 test modules | End-to-end: sensors → SQLite → FastAPI → dashboard |
| Config | `app.toml`, `devices.toml`, `plants.toml`, `sensors.toml` | `settings.toml`, `thresholds.toml` |
| Source tree | `core/ config/` (+ `drivers/ storage/ runtime/ web/` planned) | `sensors/ registry.py` + poller + store + web |

`PHASE1_PLAN.md` and the blueprint ask for overlapping things in incompatible
ways. The plan says "dashboard showing live readings, threshold automation."
The blueprint says the same words but means channels bound to roles, tuning in
the database, DLI-based lighting, two systemd units, and guards that can only
subtract. Claude Code built the plan, correctly, and the plan was the wrong
document to hand it.

The prototype is not wasted. It proved the sensor stack installs on Trixie, it
proved both I2C sensors read, and it has been logging real BME680 and VEML7700
data. That is worth harvesting. The code shape is not.

---

## 2. Where the prototype and the blueprint disagree

Read off the running dashboard and Claude Code's own summary. Requirement IDs
are from `docs/architecture.html`.

**Rules bind to field names, not roles.** The dashboard states its own rules:
`veml7700.lux = 73.1`, `soil_moisture.moisture_pct = 46.1`,
`bme680.temperature_c = 27.5`. Every rule names the driver that produced the
value. Move the sensor to another mux channel, swap the breakout, add a second
plant, and every rule breaks. **DATA-3, SCOPE-3** — and this is the primary
design constraint of the whole project, not a detail.

**There is no data model.** No node, zone, plant, channel or role. No
`stale_after_s`, so nothing can be reported offline (**DATA-4**). No plausible
range per channel, so nothing can be flagged rather than dropped (**SENS-3,
DATA-6**). Channels exist because a driver happened to emit them — `altitude`
is on the dashboard as a first-class reading, derived from pressure against an
assumed sea-level constant, declared by nobody. **DATA-1, DATA-2, DATA-5.**

**One process.** FastAPI's `lifespan` starts the poller. A dashboard crash or a
UI deploy takes the control loop with it. The blueprint's §03 exists precisely
to prevent this: two systemd units, SQLite as the message bus, neither importing
the other. **ARCH-1, ARCH-2.**

**Tuning lives in a file.** `thresholds.toml` holds the moisture and lux
numbers. The blueprint's operations table puts hardware topology in TOML under
git and tuning in SQLite, editable from a phone, applying next tick. **UI-3,
OPS table §10.**

**Lighting is a lux threshold.** `lux < 8000 → grow light on`. The blueprint
integrates measured illuminance into a daily light integral per plant, resets at
local midnight, and supplements only against a projected end-of-day shortfall
inside the photoperiod. A lux threshold runs the lamp because a cloud passed.
**CTRL-4, CTRL-5, CTRL-6, CTRL-7.**

**No VPD.** Not computed, not stored, not on the dashboard. It is the physical
driver of transpiration and the single strongest feature Phase 2 has, and it
cannot be backfilled from rolled-up inputs. **CTRL-10, ML-1.**

**Safety is a checklist inside the engine, not three independent layers.** The
pulse/cooldown/daily-cap envelope is checked by the rules engine before firing.
The blueprint enforces `max_on_seconds` *inside the driver* whatever the caller
asks, runs a watchdog thread independent of the loop, and ships a standalone
`panic_off.py` that imports nothing from the application and runs from
`ExecStopPost`. Two of those three paths reach the hardware without the loop
participating — which is the condition under which a stuck valve happens.
**SAFE-1 through SAFE-8.**

**Storage is a table, not a tier.** No numbered migrations with a
`schema_migrations` record, no idempotent rollup storing min/max/mean/count, no
`VACUUM INTO` backup, no joined export. **STOR-1 through STOR-5.**

**The soak gate was skipped.** `watering` is live on the dashboard with
`moisture < 30%`, hysteresis to 38%, a 5 s pulse and a 180 s daily cap. Those
numbers were invented. Both `docs/architecture.html` §06 and
`docs/autonomous-build.md` §1 say the same thing: the Seesaw reports roughly
200–2000 capacitance counts, "dry" depends entirely on soil mix and probe depth,
and thresholds come from days of logged readings on the actual plant. Building
the control layer against guessed numbers produces something that runs without
working.

**Soil moisture is a mock reporting a percentage.** The Seesaw does not report
percent; it reports counts. A mock that emits the unit the real sensor does not
emit will hide the conversion bug rather than surface it. **SENS-7** also wants
simulated drying modelled from VPD and light, not noise — the sparkline shows a
smooth ramp.

**One poll interval for everything.** The footer says `poll 10s`. The blueprint
sets rates per channel: 10 s for light and air, 60 s for soil, because soil does
not move that fast and the raw tier is retained for seven days.

Nothing in that list is a bug in the prototype. The prototype does what
`PHASE1_PLAN.md` asked. It is the wrong target.

---

## 3. The decision

**Do not patch the prototype toward the blueprint.** Every item above is
structural — the data model, the process split, where tuning lives, what a rule
binds to. Retrofitting them one at a time means rewriting every file while
keeping a dashboard alive on top, which is slower and less honest than building
the layers in order against gates that can be checked.

**The blueprint repo is the build.** It already has layer 01 green, the layer
gates in `docs/autonomous-build.md`, the `/next-layer` command, `autobuild.sh`,
and a permission envelope in `setup/claude/settings.json`. Run it as designed:
`02 → 03 → 04a → 05 → 06`, then the soak, then `04b`.

**Keep the prototype running until layer 05 needs port 8000.** It is logging
real air and light data and it costs nothing. Then stop it, tag it, and leave it
in place as the spike it is.

---

## 4. Harvest before moving on

Five things the prototype knows that the blueprint repo does not. Get them out
of it first — they are the only reason to open its source again.

1. **The install workaround.** `bootstrap.sh` encodes `adafruit-lgpio` plus
   `--no-deps`, because `adafruit-blinka` wants `lgpio` which wants swig and
   sudo. Carry this into `docs/pi-setup.md` §3 as a note. Then verify **PLAT-2**
   holds — `RPi.GPIO` must not appear anywhere in the dependency tree, and
   `--no-deps` installs are exactly how it sneaks in. `pip list | grep -i rpi`
   and `pipdeptree` both, before layer 03 is called done.
2. **Which addresses actually answered**, and at which address the BME680 sat —
   `0x76` or `0x77`. `config/sensors.toml` guesses; the bus knows. This is the
   one edit `docs/autonomous-build.md` §2 permits to that file, and it must be
   said in the commit message.
3. **The VEML7700 gain and integration time** the prototype used. **SENS-5**
   requires these set explicitly and recorded with the reading. If the prototype
   left them at driver default, note that the recorded lux values are not
   comparable to what layer 03 will produce.
4. **Observed value ranges**, for setting plausible ranges honestly in layer 03:
   gas resistance around 200 kΩ, pressure around 979 hPa, indoor lux from about
   70 at night to whatever the daytime peak reached, air temperature around
   27 °C. Real numbers from this room beat invented bounds.
5. **The prototype's SQLite file.** Copy it somewhere safe. It is not soak data
   — the soil channel is a mock and the schema is not the blueprint's — but the
   air and light history is real and may be worth replaying against layer 02's
   rollup job as a test fixture.

Nothing else. Not the rules engine, not the actuator classes, not the poller,
not the dashboard JavaScript.

---

## 5. Sequence from here

```
now        harvest the five items above, then build layers 02 → 03
           (both are laptop-testable; the Pi is only needed for `doctor`)

then       wire the Seesaw and run `smartgarden doctor` — this is the
           critical path, because the seven-day soak cannot start until the
           soil sensor is real, and nothing past 04a is meaningful without it

then       04a → 05 → 06        stage A ends: dashboard live, nothing can act
                                stop the prototype before 05 takes port 8000

then       stage B, ≥7 days     automation_enabled = false, water normally,
                                soak-report.sh nightly, then a person reads
                                the plateaus and edits config/plants.toml

then       04b                  guards, watchdog, panic-off, automation
```

Wire the Seesaw now, in parallel with layers 02 and 03. Everything downstream
waits on the soak, and the soak waits on the sensor.

---

## 6. What to say to Claude Code on the Pi

> **Superseded 2026-09-08 by `START-HERE.md` §2**, which says the same things
> and adds the repository authority Claude Code now has: it pushes, opens pull
> requests and merges to `main` itself, with CI as the gate rather than a
> person. Paste that instead. The text below is kept because the three
> requirements it insists on have not changed.

Paste this at the start of a fresh session in `~/SmartGarden` (the blueprint
repo, not the prototype directory):

> There is an existing SmartGarden prototype running on this Pi at port 8000,
> built from a different brief. It is not the system we are building and it is
> not to be patched, imported from, or used as a reference for structure. This
> repository is the build.
>
> Read `docs/architecture.html` — the 72 numbered requirements are the contract.
> Then `CLAUDE.md` for the hard rules and `docs/autonomous-build.md` for the
> layer gates and the operating contract. Where they disagree, the blueprint
> wins.
>
> Before building anything, do the harvest in §4 of `docs/realign.md`: get the
> install workaround, the confirmed I2C addresses, the VEML7700 gain and
> integration time, the observed value ranges, and a copy of the prototype's
> SQLite file. Report what you found. If the BME680 answered at an address that
> disagrees with `config/sensors.toml`, that is the one edit to that file you
> are allowed, and say so in the commit message.
>
> Then `/next-layer 02`.
>
> Two things to hold on to as you go, because the prototype got both wrong and
> they are the requirements everything else rests on: a rule or a UI element
> names a **role** in a zone, never a driver, a field or an I2C address
> (DATA-3, SCOPE-3); and nothing in stages A builds an actuation path at all
> (`docs/autonomous-build.md` §1). If a gate looks like it needs a moisture
> threshold, that is the soak gate and the answer is to stop, not to guess.

For layers after 02, the `/next-layer NN` command already carries the gate — no
further briefing needed.

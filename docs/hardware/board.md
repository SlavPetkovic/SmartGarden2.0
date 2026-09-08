# SmartGarden HAT — board reference

Recovered from the fabrication package, not from memory. Everything below was
extracted from the Gerbers in `gerbers/` by reading the copper and drill files
and tracing connectivity; nothing here is inferred from the photograph.

| | |
|---|---|
| Project | `raspberry_pi_hat.PrjPcb` · document `PCB3.PcbDoc` |
| Tool | Altium Designer 20.0.13 |
| Gerbers generated | 21 April 2024, 17:04 |
| Fab order | `5292917A_Y4` · 2 layer · FR-4 · 1 oz copper both sides |
| Board outline | 65.28 × 72.39 mm, chamfered corners |
| Holes | 77, all plated |
| DRC | clean at export |

---

## 1. What is on it

| Silkscreen | Footprint | Drill | Notes |
|---|---|---|---|
| `40 Headers` | 2 × 20, 2.54 mm pitch | 1.02 mm | Pi GPIO header |
| `BME680` | 1 × 7, 2.54 mm | 0.90 mm | Adafruit BME680 breakout |
| `VEML7700` | 1 × 5, 2.54 mm | 0.90 mm | Adafruit VEML7700 breakout |
| `moisture sensor` | 1 × 4, **2.00 mm** pitch | 0.80 mm | JST-PH — Adafruit STEMMA soil sensor cable |
| `5V` | 1 × 5, 2.54 mm | 1.20 mm | 5 V fan-out |
| `Ground` | 1 × 5, 2.54 mm | 1.20 mm | GND fan-out |
| `Relays` | 1 × 2, **5.08 mm** pitch | 1.10 mm | signal only — screw-terminal pitch |
| `D1` + `220R` | LED 2.54 mm + axial 7.62 mm | 1.27 / 0.85 mm | power indicator across 5 V |
| — | 4 × mounting | 2.75 mm | 49.0 × 58.0 mm — **exact HAT pattern** |

The pin counts settle what the breakouts are. Seven pins in the BME680 position
matches the Adafruit breakout's `VIN · 3Vo · GND · SCK · SDO · SDI · CS`, and the
traced connectivity lands on exactly those pins in that order. Five in the
VEML7700 position matches `VIN · 3Vo · GND · SCL · SDA`, again confirmed by the
copper. Four pins at 2.00 mm is a JST-PH — the Adafruit STEMMA cable, which is
what the STEMMA soil sensor ships with.

---

## 2. Netlist

Six nets, traced from the top and bottom copper joined through plated holes.
Header pins are given as physical pin numbers.

### 5V — Pi pin 2

Reaches: BME680 `VIN`, VEML7700 `VIN`, moisture connector pin 2, the 5-way `5V`
header, and the 220 Ω resistor feeding `D1`.

### GND — Pi pin 39

Reaches: BME680 `GND`, VEML7700 `GND`, moisture connector pin 1, the 5-way
`Ground` header, and the `D1` cathode.

### SDA — Pi pin 3 (GPIO2)

Reaches: BME680 `SDI`, VEML7700 `SDA`, moisture connector pin 3.

### SCL — Pi pin 5 (GPIO3)

Reaches: BME680 `SCK`, VEML7700 `SCL`, moisture connector pin 4.

### RELAY 1 — Pi pin 18 (**GPIO24**)

Goes to the `Relays` terminal at the **square pad** (the left-hand one when the
silkscreen reads right way up), plus one 0.71 mm test point.

### RELAY 2 — Pi pin 16 (**GPIO23**)

Goes to the `Relays` terminal at the **round pad** (right-hand).

Unconnected by design: both `3Vo` pins, and every other header pin. The board
uses one 5 V pin and one ground pin and nothing else.

### Why the pin mapping is certain

Four independent checks agree, which is what makes this safe to wire from:

1. SDA and SCL land on **adjacent rows of the same column** — the only place on a
   Pi header where the two I²C lines can sit is pins 3 and 5.
2. That fixes the column as the odd pins, which puts the other column's first
   row on pin 2 — and that net is the one feeding every `VIN`. 5 V, as expected.
3. The last row of the odd column is then pin 39, and that net feeds every
   `GND`.
4. The two relay nets land on pins 16 and 18 — **GPIO23 and GPIO24** — which are
   exactly the pins hard-coded in the original `pi_actuator.py`
   (`light_pin = 24`, `pump_pin = 23`).

Four constraints, one consistent solution. Reversing the numbering in either
direction breaks all four at once.

---

## 3. Wiring it

Sensors are powered from **5 V, not 3.3 V**. For the two breakouts that is fine:
both the Adafruit BME680 and VEML7700 boards carry their own 3.3 V regulator and
level-shift their I²C, so their bus pull-ups sit on the regulated 3.3 V rail, not
on VIN. Their `3Vo` pins are regulator *outputs* — leave them unconnected, as the
board does.

### ⚠ The soil sensor is the exception, and the board gets it wrong

The Adafruit STEMMA soil sensor has **no regulator and no level shifting**. Its
10 kΩ SDA and SCL pull-ups go **directly to VIN**. Adafruit's own guidance is to
"use the same power voltage as you would for I2C logic" — and the Pi's I²C logic
is 3.3 V.

This board puts the moisture connector's VIN on the **5 V** net, so as designed
the Seesaw's pull-ups drag SDA and SCL — GPIO2 and GPIO3 on the Pi — toward 5 V.
Against the Pi's own 1.8 kΩ pull-ups to 3.3 V the bus idles near **3.56 V**. That
sits under the SoC's 3.8 V absolute maximum, so it will very likely run rather
than fail outright, but it is above the 3.3 V rail and outside spec, and it is not
something to leave on a system meant to sit unattended for weeks watering plants.

Three ways out, in order of preference:

1. **Don't use the HAT connector for the soil sensor.** Run its four wires to the
   Pi header directly and take VIN from **3.3 V (pin 1)**. Costs nothing, fixes it
   completely, and is the right move while the soak is the only thing that matters.
2. **Cut the connector's VIN trace and jumper it to 3.3 V.** The board uses no
   3.3 V net at all today, so this means a wire from header pin 1 or 17. The
   proper fix if the HAT is populated and you want one tidy assembly.
3. Level shifter on SDA/SCL. Correct, and more parts than the problem deserves.

Note that none of this is a respin. Option 2 is one cut and one wire on the
existing board.

**Decision, 2026-09-08 — running as designed, on 5 V.** Bus verified with
`i2cdetect`: `0x10`, `0x36` and `0x77` all answer, and the soil sensor reads.
Accepted knowingly, on the grounds that a week of soil data matters more right
now than the margin does. Revisit if `soil_moisture` starts accumulating read
failures in the health view — that is what SENS-2 and DATA-4 will surface it as,
and it is the signal to come back to this section rather than to debug the driver.

Fold the real fix into the board revision whenever the Altium source turns up or
gets redrawn: the moisture connector belongs on 3.3 V, and a 3.3 V net should
exist at all.

The connector's order is GND · VIN · SDA · SCL counting from the pin nearest the
board edge — confirmed both from the copper and against Adafruit's pinout, which
uses that same order. The STEMMA cable is black · red · white · green in that
order. **Check your cable against both before plugging it in** — a reversed 4-pin
JST puts power on the sensor's ground pin.

The `Relays` terminal carries **signal only**. The relay module takes its own 5 V
and ground from the two 5-way fan-out headers. That means:

- The module must have its own driver transistors or optoisolators. A bare relay
  coil cannot be driven from a GPIO pin — 3.3 V at a few milliamps will not pull
  it in, and trying will damage the pin.
- Most 2-channel opto modules are **active-low**, which is what `active_low = true`
  in the old code assumed. Confirm yours before the first live test.
- Both relay coils draw their current through the single 5 V pin and single
  ground pin the board uses. Two coils at roughly 70 mA each is within what one
  header pin will carry, but there is no second ground for return current. Worth
  knowing if you ever add a third channel.

For `config/devices.toml`, once you get to that layer:

```toml
# pins confirmed from the recovered Gerbers, 2026-09-08
# grow light -> Relays terminal 1 (square pad)
# pump       -> Relays terminal 2 (round pad)
# gpiozero + lgpio pin factory — RPi.GPIO cannot address Pi 5 GPIO (PLAT-2)
grow_light = { gpio = 24, active_low = true, max_on_seconds = ... }
water_pump = { gpio = 23, active_low = true, max_on_seconds = ... }
```

`max_on_seconds` is deliberately left blank — it is a safety constant and belongs
to a person, per `docs/BUILD-PLAN.md` §3.

### The 30-second check before you trust any of this

With the HAT off the Pi, a multimeter on continuity:

- square relay pad ↔ header pin 18 → beeps
- round relay pad ↔ header pin 16 → beeps
- `5V` fan-out header ↔ header pin 2 → beeps
- `Ground` fan-out header ↔ header pin 39 → beeps

Four beeps and the table above is confirmed on the physical board rather than in
a file. Pin 18 is the ninth pin down the even-numbered row counting from pin 2.

---

## 4. Mechanical

The mounting holes are at the **exact HAT pattern**, 49.0 × 58.0 mm, so it bolts
to a Pi 5 on all four standoffs and the header lines up.

The outline, though, is **65.28 × 72.39 mm** against the standard HAT's
65 × 56.5 mm — roughly 16 mm longer on the axis running along the Pi's long edge
and 9 mm wider across. The board overhangs the Pi on at least two sides. That is
free space in the air on the SD-card and GPIO sides, but check clearance over the
USB and Ethernet stack before bolting it down, since those connectors stand about
13 mm proud and a standard HAT is sized to clear them exactly.

---

## 5. What was recovered, and what was not

`gerbers/` holds the complete fabrication set — both copper layers, both
soldermasks, both pastes, top silkscreen, board outline, drill file, drill
report, aperture list, design rules and the DRC report. That is enough to
**re-order the board as-is** from any fab house.

`fab-order-5292917A_Y4.zip` is the original package as downloaded, kept intact.

What is missing is the Altium source: `raspberry_pi_hat.PrjPcb`, `PCB3.PcbDoc`
and the schematic. Gerbers are an output format, so the source cannot be
regenerated from them without redrawing. Two consequences:

- **Re-ordering the existing design: fine.** Send `gerbers/` as-is.
- **Changing the design: means redrawing it.** With the netlist in §2 that is
  perhaps an hour in KiCad, and the result would be a source you actually keep.

The source files are worth one more look before accepting that. They were never
in `OneDrive\PROJECTS`, `Documents` or `Downloads` — the whole tree was searched.
Places still worth checking: the machine the board was drawn on in April 2024 if
it was not this one; Altium's own project folder, usually
`Documents\Altium\Projects`; and Altium 365 / Workspace if the project was ever
pushed to a cloud workspace, which is where an Altium project most often lives
when it is not on disk.

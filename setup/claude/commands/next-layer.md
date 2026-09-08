---
description: Build one SmartGarden layer against its acceptance gate, then ship it
argument-hint: 01 | 02 | 03 | 04a | 05 | 06 | 04b
---

Build layer **$1** of SmartGarden, and take it all the way to `main`.

1. Read `docs/BUILD-PLAN.md`. Its §5 section for layer $1 is the acceptance gate —
   every item must be true and every requirement ID it names satisfied. §3 is the
   autonomy contract and the stop conditions; both bind you.
2. Read `CLAUDE.md` for the hard rules, and the relevant section of
   `docs/architecture.html` for the requirements themselves. Where they disagree,
   `architecture.html` wins.
3. Read `docs/git-workflow.md` for what you may and may not do to this repository.
4. Work on branch `auto/layer-$1`. Create it from an up-to-date `main`:

   ```bash
   git switch main && git pull --ff-only
   git switch -c auto/layer-$1
   ```

   Never commit to `main` directly.

5. Build, then run all four checks yourself and iterate until clean:

   ```bash
   PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t .
   .venv/bin/ruff check .
   .venv/bin/mypy
   .venv/bin/python scripts/gate.py
   ```

6. Commit with a message naming the requirement IDs satisfied.
7. Then run `/ship` — push, open the pull request, wait for CI, merge on green,
   tag the layer. You have the authority to complete that without asking.

Do not weaken a test, widen a plausible range, raise a `max_on_seconds`, or relax a
safety constant to make a gate pass. Do not edit a check in `scripts/` or
`.github/workflows/` to make today's work merge — a change to the gate goes in its
own pull request. If the gate cannot be passed honestly, write
`.autobuild/BLOCKED-$1.md` saying what is in the way, and stop — that is a good
outcome, not a failure.

Three things hold across every layer:

- A rule or UI element names a **role** in a zone, never a driver, a field name or an
  I2C address (DATA-3, SCOPE-3).
- Measurements are **rows, not columns** (DATA-1).
- Nothing in stage A (layers 01–06) builds an actuation path. A gate that seems to need
  a moisture threshold is the soak gate — stop, do not guess.

Before you start, tell me in two or three lines what you are about to build and what
the gate requires. Then go.

## What this is

<!-- Two or three sentences. What now works that did not before. -->

## Requirements satisfied

<!-- Requirement IDs from docs/architecture.html, one line each on how.
     e.g. SENS-5 — gain and integration time set explicitly and stored
     alongside each VEML7700 reading, so lux values are comparable. -->

## Gate

<!-- The acceptance gate for this change. For a layer, BUILD-PLAN.md §5. -->

- [ ] every item in that gate is true
- [ ] `python scripts/gate.py` clean locally
- [ ] no actuation path added (stage A only)

## What I was unsure about

<!-- The honest section, and the one that matters most in a repository where
     pull requests merge themselves. What was guessed. What was assumed about
     the physical world — which pin, which address, how wet is wet. What a
     person should look at before trusting this.

     "Nothing" is a suspicious answer on a substantial change. -->

---

<!-- If this change touches tuning, a safety constant, a contract document, or
     removes tests, one of these lines is required. Reason on the same line;
     a bare token does not clear the tripwire. See docs/git-workflow.md §4.

TUNING-CHANGE:
SAFETY-CHANGE:
CONTRACT-CHANGE:
TEST-REMOVAL:

     LINT-ONLY: (reason) -- only for a mechanical no-op (ruff format / --fix,
     a type-annotation fix) that spans a gate file and src/ or tests/. It
     suppresses the SEPARATE-PULL-REQUEST tripwire and nothing else.
-->

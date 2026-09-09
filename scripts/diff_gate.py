#!/usr/bin/env python3
"""Tripwires on the shape of a change, not on the code itself.

Three things in this repository are dangerous to change quietly:

  1. tuning       -- config/app.toml, config/plants.toml, config/devices.toml
                     hold automation_enabled, the moisture thresholds and the
                     driver selection. Those three files are what stand between
                     a simulation and water on the floor.
  2. safety       -- max_on_seconds, cooldowns, daily budgets, plausible ranges.
                     A guard may only ever subtract (SAFE-1). Widening one is
                     how a stuck valve happens.
  3. test cover   -- a suite that shrank is the cheapest possible way past a
                     red build.

None of these are forbidden. All three are sometimes exactly right. What is
forbidden is doing one of them without saying so where a person reading the
pull request will see it.

So: if the diff touches one, the pull request body must carry the matching
token and a reason on the same line.

    TUNING-CHANGE: soak data from 2026-09-14..21 puts the dry plateau at 640
                   counts, not the placeholder 800.
    SAFETY-CHANGE: max_on_seconds 5 -> 8, because the 5 s pulse never wet the
                   full root ball; measured, not guessed.
    TEST-REMOVAL:  test_altitude_channel deleted -- altitude was never a
                   declared channel (DATA-5), the test asserted a bug.

Usage:

    python scripts/diff_gate.py --base origin/main --body-file pr-body.txt
    python scripts/diff_gate.py --base origin/main          # body from stdin

Exit 0 clear, 1 a tripwire fired without its token.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

TUNING_FILES = {
    "config/app.toml",
    "config/plants.toml",
    "config/devices.toml",
}

# sensors.toml is deliberately absent: correcting an I2C address that
# `smartgarden doctor` proved wrong is an allowed autonomous edit
# (BUILD-PLAN section 3), and gating it would make honest work harder.

CONTRACT_FILES = {
    "docs/architecture.html",
    "docs/BUILD-PLAN.md",
    "CLAUDE.md",
    "docs/git-workflow.md",
}

# These four are what the build is judged against: the 72 requirements, the
# layer gates, the hard rules, and this contract. Editing one is allowed --
# a requirement can be wrong, and discovering that is real work. Editing one
# in the same change as the code it judges is how a gate passes by having the
# gate moved. The token is what separates the two.

GATE_FILES = re.compile(r"^(?:\.github/workflows/|scripts/(?:gate|diff_gate)\.py$)")

SAFETY_PATTERN = re.compile(
    r"\bmax_on_seconds\b"
    r"|\bmin_off_seconds\b"
    r"|\bcooldown\w*\b"
    r"|\bdaily_(?:cap|budget|limit)\w*\b"
    r"|\bplausible\w*\b"
    r"|\bwatchdog\w*\b"
    r"|\bpanic_off\b",
    re.IGNORECASE,
)

TEST_DEF = re.compile(r"^\s*def\s+test_\w+")


@dataclass(slots=True)
class Tripwire:
    token: str
    what: str
    detail: list[str]


def run(*args: str) -> str:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 and not result.stdout:
        cmd = " ".join(args)
        print(f"warning: {cmd} failed: {result.stderr.strip()}", file=sys.stderr)
    return result.stdout


def changed_files(base: str) -> list[str]:
    out = run("git", "diff", "--name-only", f"{base}...HEAD")
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def diff_body(base: str) -> str:
    return run("git", "diff", "--unified=0", f"{base}...HEAD")


def net_test_change(base: str) -> int:
    """Positive means tests were added, negative means the suite shrank."""
    added = removed = 0
    for line in diff_body(base).splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and TEST_DEF.match(line[1:]):
            added += 1
        elif line.startswith("-") and TEST_DEF.match(line[1:]):
            removed += 1
    return added - removed


def touched_safety_lines(base: str) -> list[str]:
    hits: list[str] = []
    current = ""
    for line in diff_body(base).splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line[:1] in "+-" and SAFETY_PATTERN.search(line[1:]):
            hits.append(f"{current}: {line.strip()[:110]}")
    return hits[:12]


def has_token(body: str, token: str) -> bool:
    # The token must be followed by something other than whitespace on the
    # same line: a bare "SAFETY-CHANGE:" is not a reason.
    match = re.search(rf"^\s*{re.escape(token)}\s*:?(.*)$", body, re.MULTILINE)
    return bool(match and match.group(1).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="base ref to diff against")
    parser.add_argument("--body-file", help="file containing the pull request body")
    args = parser.parse_args()

    if args.body_file:
        with open(args.body_file, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    else:
        body = sys.stdin.read() if not sys.stdin.isatty() else ""

    tripwires: list[Tripwire] = []
    files = set(changed_files(args.base))

    touched_tuning = sorted(files & TUNING_FILES)
    if touched_tuning and not has_token(body, "TUNING-CHANGE"):
        tripwires.append(
            Tripwire(
                "TUNING-CHANGE",
                "this change edits tuning that automation acts on",
                touched_tuning,
            )
        )

    safety_lines = touched_safety_lines(args.base)
    if safety_lines and not has_token(body, "SAFETY-CHANGE"):
        tripwires.append(
            Tripwire(
                "SAFETY-CHANGE",
                "this change touches a safety constant",
                safety_lines,
            )
        )

    touched_contract = sorted(files & CONTRACT_FILES)
    if touched_contract and not has_token(body, "CONTRACT-CHANGE"):
        tripwires.append(
            Tripwire(
                "CONTRACT-CHANGE",
                "this change edits a document the build is judged against",
                [
                    *touched_contract,
                    "A requirement can be wrong. Say which one, and what proved it,",
                    "and put it in its own pull request -- not alongside the code",
                    "whose gate it moves.",
                ],
            )
        )

    touched_gate = sorted(f for f in files if GATE_FILES.match(f))
    work_files = sorted(
        f for f in files if f.startswith(("src/", "tests/", "migrations/", "web/"))
    )
    if touched_gate and work_files:
        tripwires.append(
            Tripwire(
                "SEPARATE-PULL-REQUEST",
                "this change edits the gate and the work the gate checks, together",
                [
                    *touched_gate,
                    "alongside:",
                    *work_files[:6],
                    "Split them. This one has no token -- "
                    "see docs/git-workflow.md section 3.",
                ],
            )
        )

    delta = net_test_change(args.base)
    if delta < 0 and not has_token(body, "TEST-REMOVAL"):
        tripwires.append(
            Tripwire(
                "TEST-REMOVAL",
                f"this change removes {-delta} test(s) net",
                ["A shrinking suite is the cheapest way past a red build."],
            )
        )

    if not tripwires:
        print("No tripwires fired.")
        if delta > 0:
            print(f"(+{delta} test(s) in this change.)")
        return 0

    print("Tripwires fired on the shape of this change.\n")
    for wire in tripwires:
        print(f"  {wire.token}  --  {wire.what}")
        for item in wire.detail:
            print(f"      {item}")
        print()

    needs_token = [w for w in tripwires if w.token != "SEPARATE-PULL-REQUEST"]
    if needs_token:
        print("Add a line to the pull request body for each, with the reason:")
        print()
        for wire in needs_token:
            print(f"    {wire.token}: <why this is correct, and what evidence says so>")
        print()
        print("A bare token with nothing after it does not clear a tripwire.")
        print()

    print("None of this is forbidden. It is required to be visible.")
    print("See docs/git-workflow.md section 4.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

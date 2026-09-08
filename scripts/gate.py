#!/usr/bin/env python3
"""Structural guard rails for SmartGarden.

These are the invariants from CLAUDE.md and docs/architecture.html that a
machine can check. They run in CI on every pull request, and locally with:

    PYTHONPATH=src python3 scripts/gate.py

Standard library only, on purpose: this must run before anything is installed,
and it must run on the Pi's control service environment, which has no
third-party dependencies (CLAUDE.md hard rule 7).

Exit codes: 0 all clear, 1 one or more invariants broken.

Each check names the requirement ID it enforces. If a check is wrong about a
requirement, fix the check in the same pull request that proves it wrong, and
say so in the commit message. Do not delete a check to make a gate pass --
docs/BUILD-PLAN.md section 3 covers why.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "smartgarden"
CONFIG = REPO / "config"
TESTS = REPO / "tests"


@dataclass(slots=True)
class Result:
    name: str
    requirement: str
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# ---------------------------------------------------------------------------
# ARCH-4 -- core/ is pure.
#
# core/ imports nothing from drivers, storage, runtime or web, and performs no
# I/O. This is what makes the whole decision path testable on a laptop in 30
# milliseconds. A single `open()` in core is the beginning of the end of that.
# ---------------------------------------------------------------------------

FORBIDDEN_CORE_PACKAGES = {"drivers", "storage", "runtime", "web", "config"}
FORBIDDEN_CORE_MODULES = {
    "sqlite3",
    "socket",
    "http",
    "urllib",
    "requests",
    "httpx",
    "pathlib",
    "os",
    "shutil",
    "subprocess",
    "tomllib",
    "asyncio",
    "threading",
}
FORBIDDEN_CORE_CALLS = {"open", "input", "print"}


def _module_head(name: str) -> str:
    return name.split(".", 1)[0]


def check_core_purity() -> Result:
    r = Result("core/ is pure", "ARCH-4, CLAUDE.md hard rule 2")
    for path in python_files(SRC / "core"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            r.failures.append(f"{rel(path)}: cannot parse: {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = _module_head(alias.name)
                    if head in FORBIDDEN_CORE_MODULES:
                        r.failures.append(
                            f"{rel(path)}:{node.lineno}: core imports {alias.name!r} "
                            f"-- core performs no I/O"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    # Relative import: `from ..storage import x` inside core.
                    parts = (node.module or "").split(".")
                    if parts and parts[0] in FORBIDDEN_CORE_PACKAGES:
                        r.failures.append(
                            f"{rel(path)}:{node.lineno}: core imports from "
                            f"{parts[0]!r} -- core depends on nothing"
                        )
                    continue
                module = node.module or ""
                head = _module_head(module)
                if head in FORBIDDEN_CORE_MODULES:
                    r.failures.append(
                        f"{rel(path)}:{node.lineno}: core imports from {module!r} "
                        f"-- core performs no I/O"
                    )
                if module.startswith("smartgarden."):
                    sub = module.split(".")[1]
                    if sub in FORBIDDEN_CORE_PACKAGES:
                        r.failures.append(
                            f"{rel(path)}:{node.lineno}: core imports "
                            f"smartgarden.{sub} -- core depends on nothing"
                        )
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CORE_CALLS:
                    r.failures.append(
                        f"{rel(path)}:{node.lineno}: core calls {fn.id}() "
                        f"-- core performs no I/O"
                    )
                # datetime.now() / datetime.utcnow(): core reads no clock; the
                # time it reasons about is passed in, which is what makes a
                # decision reproducible in a test.
                if isinstance(fn, ast.Attribute) and fn.attr in {"now", "utcnow", "today"}:
                    owner = fn.value
                    if isinstance(owner, ast.Name) and owner.id in {"datetime", "date", "time"}:
                        r.failures.append(
                            f"{rel(path)}:{node.lineno}: core reads the clock via "
                            f"{owner.id}.{fn.attr}() -- pass the time in instead"
                        )
    return r


# ---------------------------------------------------------------------------
# PLAT-1 -- RPi.GPIO does not work on the Pi 5.
#
# Its GPIO sits behind the RP1 south bridge. gpiozero with the lgpio pin
# factory is the supported path. RPi.GPIO sneaks in as a transitive dependency
# of adafruit-blinka, which is why --no-deps installs are called out in
# docs/pi-setup.md. Catch it in source and in the declared dependency tree.
# ---------------------------------------------------------------------------


def check_no_rpi_gpio() -> Result:
    r = Result("no RPi.GPIO", "PLAT-1, CLAUDE.md hard rule 1")
    pattern = re.compile(r"\bRPi\.GPIO\b|\bimport\s+RPi\b|\bRPi_GPIO\b|\brpi[-_]?gpio\b", re.I)

    for path in python_files(REPO / "src") + python_files(TESTS):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # a comment saying "not RPi.GPIO" is the right comment
            if pattern.search(line):
                r.failures.append(
                    f"{rel(path)}:{lineno}: references RPi.GPIO -- "
                    f"use gpiozero with the lgpio pin factory"
                )

    pyproject = REPO / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        declared: list[str] = list(project.get("dependencies", []))
        for extra, deps in (project.get("optional-dependencies") or {}).items():
            declared.extend(f"[{extra}] {d}" for d in deps)
        for dep in declared:
            if pattern.search(dep):
                r.failures.append(f"pyproject.toml declares {dep!r} -- RPi.GPIO is not usable")
    return r


# ---------------------------------------------------------------------------
# CLAUDE.md hard rule 7 -- the control service has no third-party dependencies.
#
# A failed dependency install must not be able to stop watering. Web and
# hardware libraries are opt-in extras.
# ---------------------------------------------------------------------------


def check_no_base_dependencies() -> Result:
    r = Result("control service has no third-party dependencies", "CLAUDE.md hard rule 7")
    pyproject = REPO / "pyproject.toml"
    if not pyproject.is_file():
        r.failures.append("pyproject.toml is missing")
        return r
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if deps:
        r.failures.append(
            f"pyproject.toml [project].dependencies is not empty: {deps!r}. "
            f"Move these into an optional extra (web, pi or dev)."
        )
    return r


# ---------------------------------------------------------------------------
# BUILD-PLAN section 3 -- a test may not be weakened, skipped or xfailed to
# pass a gate.
#
# This is the check that makes "CI is the gate" mean something. Without it the
# cheapest way past a red build is to silence the test that went red.
# ---------------------------------------------------------------------------

SKIP_MARKERS = re.compile(
    r"@(?:unittest\.)?(?:skip|skipIf|skipUnless|expectedFailure)\b"
    r"|@pytest\.mark\.(?:skip|skipif|xfail)\b"
    r"|self\.skipTest\(",
)


def check_no_silenced_tests() -> Result:
    r = Result("no silenced tests", "BUILD-PLAN section 3")
    allow = re.compile(r"#\s*gate:\s*allow-skip\b")
    for path in python_files(TESTS):
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, 1):
            if not SKIP_MARKERS.search(line):
                continue
            # A hardware test that cannot run on a laptop is a legitimate skip,
            # but it must say so on the same line so the reason is reviewable.
            window = "\n".join(lines[max(0, lineno - 3) : lineno + 2])
            if allow.search(window) or "hardware" in window.lower():
                continue
            r.failures.append(
                f"{rel(path)}:{lineno}: test is skipped or expected to fail. "
                f"If this is a hardware test, mark it `# gate: allow-skip` "
                f"with the reason on the line above."
            )
    return r


# ---------------------------------------------------------------------------
# Stage A builds no actuation path -- BUILD-PLAN section 3, autonomous-build
# section 1.
#
# Until layer 04b, nothing may reach a physical output, and automation stays
# off. The soak gate sits between them for a reason: thresholds derived from
# days of real readings, not from a number someone picked.
# ---------------------------------------------------------------------------


def check_automation_disabled() -> Result:
    r = Result("automation is off", "BUILD-PLAN section 3, OPS-4")
    app = CONFIG / "app.toml"
    if not app.is_file():
        return r
    if (REPO / ".stage-b-complete").is_file():
        return r  # the soak is done and a person said so; 04b may enable it
    data = tomllib.loads(app.read_text(encoding="utf-8"))

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else key
                if key == "automation_enabled" and value is True:
                    r.failures.append(
                        f"config/app.toml: {here} = true, but the soak gate has "
                        f"not been signed off (no .stage-b-complete file). "
                        f"Stage A never actuates."
                    )
                walk(value, here)

    walk(data)
    return r


CHECKS = (
    check_core_purity,
    check_no_rpi_gpio,
    check_no_base_dependencies,
    check_no_silenced_tests,
    check_automation_disabled,
)


def main() -> int:
    results = [check() for check in CHECKS]
    width = max(len(r.name) for r in results)
    failed = 0

    for r in results:
        status = "ok  " if r.ok else "FAIL"
        print(f"{status}  {r.name.ljust(width)}   {r.requirement}")
        for failure in r.failures:
            print(f"        {failure}")
            failed += 1

    print()
    if failed:
        print(f"{failed} guard rail violation(s). These are correctness bugs, not style.")
        print("Fix the cause. Do not delete the check -- see docs/BUILD-PLAN.md section 3.")
        return 1
    print("All structural guard rails hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

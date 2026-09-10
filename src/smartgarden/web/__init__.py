"""Layer 5: the JSON API (API-1...4, ARCH-1...3, ARCH-6, OPS-1...3).

Deliberately empty of imports. Importing most of this package's modules
(`app`, `routes`, `auth`, `deps`, `schemas`) pulls in FastAPI, pydantic and
uvicorn -- the `[web]` extra, never the control service's base dependency
set (CLAUDE.md hard rule 7) -- but `web/timeseries.py` is plain stdlib on
purpose (its own docstring explains why), and re-exporting `create_app`
here would force every import of `smartgarden.web.timeseries` to drag
FastAPI in too, since Python always runs a package's `__init__.py` before
any of its submodules. Import `smartgarden.web.app.create_app` directly.

This package must never import `smartgarden.drivers` or
`smartgarden.runtime`: the web process cannot touch GPIO or I2C (ARCH-2,
ARCH-3), and the two processes communicate only through SQLite (ARCH-1) --
neither one imports the other.
"""

from __future__ import annotations

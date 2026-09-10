"""Layer 5: the JSON API (API-1...4, ARCH-1...3, ARCH-6, OPS-1...3).

Importing this package imports FastAPI, pydantic and uvicorn -- the `[web]`
extra, never the control service's base dependency set (CLAUDE.md hard rule
7). `smartgarden.cli`'s `web` subcommand imports this module lazily, inside
the command function, so that running `smartgarden config check` or
`smartgarden run` never requires these to be installed at all.

This package must never import `smartgarden.drivers` or
`smartgarden.runtime`: the web process cannot touch GPIO or I2C (ARCH-2,
ARCH-3), and the two processes communicate only through SQLite (ARCH-1) --
neither one imports the other.
"""

from __future__ import annotations

from smartgarden.web.app import create_app

__all__ = ["create_app"]

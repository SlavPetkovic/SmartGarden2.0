"""FastAPI dependencies: one connection per request (ARCH-2, ARCH-5).

The web process never shares a connection with the control loop process --
they only ever meet in the database file, in WAL mode, which is what
ARCH-5 buys. Opening and closing a connection per request is simple and
correct at this project's scale (a few plants, a handful of dashboard
viewers) and sidesteps sharing one `sqlite3.Connection` across FastAPI's
threadpool, which is not thread-safe.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

__all__ = ["get_repo"]


def get_repo(request: Request) -> Iterator[Repository]:
    conn = connect(request.app.state.db_path)
    try:
        yield Repository(conn)
    finally:
        conn.close()

"""FastAPI dependencies: one connection per request (ARCH-2, ARCH-5).

The web process never shares a connection with the control loop process --
they only ever meet in the database file, in WAL mode, which is what
ARCH-5 buys. Opening and closing a connection per request is simple and
correct at this project's scale (a few plants, a handful of dashboard
viewers).

`get_repo` is a plain (non-`async`) generator, so FastAPI runs it in
anyio's worker threadpool -- and the entry (up to `yield`) and the exit
(after the route handler returns, closing the connection) are two separate
threadpool calls that are not guaranteed to land on the same OS thread.
`check_same_thread=False` is what makes that safe: this connection is still
only ever used by one request at a time, never concurrently, just
potentially from a different thread than the one that opened it.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from smartgarden.storage.db import connect
from smartgarden.storage.repository import Repository

__all__ = ["get_repo"]


def get_repo(request: Request) -> Iterator[Repository]:
    conn = connect(request.app.state.db_path, check_same_thread=False)
    try:
        yield Repository(conn)
    finally:
        conn.close()

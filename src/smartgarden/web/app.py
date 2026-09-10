"""Assembling the FastAPI app (API-1, ARCH-1, OPS-2).

JSON only: nothing here renders HTML from application state (API-1) --
the PWA that layer 06 adds is served as static files, a separate concern
from this router. This module holds the only two pieces of process state
FastAPI needs (`app.state.config`, `app.state.db_path`); everything else
flows through `Depends`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from smartgarden.config.schema import Config
from smartgarden.web.routes import router

__all__ = ["create_app"]


def create_app(config: Config, db_path: Path) -> FastAPI:
    app = FastAPI(
        title="SmartGarden",
        description="Sensor-driven irrigation and lighting -- JSON API (API-1).",
    )
    app.state.config = config
    app.state.db_path = db_path
    app.include_router(router)
    return app

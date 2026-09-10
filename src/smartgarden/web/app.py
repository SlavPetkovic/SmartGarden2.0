"""Assembling the FastAPI app (API-1, ARCH-1, OPS-2, UI-1).

JSON only on the `/api` routes: nothing there renders HTML from application
state (API-1). The PWA is a directory of static files mounted at `/` --
`index.html`, `app.js`, the manifest and service worker are unchanged by
whatever the database currently holds; only what `app.js` fetches at
runtime varies. This module holds the only two pieces of process state
FastAPI needs (`app.state.config`, `app.state.db_path`); everything else
flows through `Depends`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from smartgarden.config.schema import Config
from smartgarden.web.routes import router

__all__ = ["STATIC_DIR", "create_app"]

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Config, db_path: Path) -> FastAPI:
    app = FastAPI(
        title="SmartGarden",
        description="Sensor-driven irrigation and lighting -- JSON API (API-1).",
    )
    app.state.config = config
    app.state.db_path = db_path
    app.include_router(router, prefix="/api")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="pwa")
    return app

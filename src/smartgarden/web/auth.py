"""Token auth: implemented, disabled by default, one config value to turn on
(API-4).

`AppConfig.api_token` being `None` -- the default -- is what disables this
entirely; there is no separate boolean, so a config that "has a token but
auth is off" cannot exist.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from smartgarden.config.schema import Config

__all__ = ["require_token"]


def require_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    config: Config = request.app.state.config
    token = config.app.api_token
    if token is None:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")

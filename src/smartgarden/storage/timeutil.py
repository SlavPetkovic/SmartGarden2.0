"""UTC, ISO-8601 timestamps in and out of SQLite (STOR-6).

SQLite has no native timestamp type; every value stored is TEXT. This module
is the one place that decides the text format, so a naive datetime never
reaches a row and every value read back is timezone-aware.
"""

from __future__ import annotations

from datetime import UTC, datetime

from smartgarden.core.errors import StorageError

__all__ = ["from_iso", "to_iso"]


def to_iso(at: datetime) -> str:
    """Render a timezone-aware datetime as UTC ISO-8601 for storage."""
    if at.tzinfo is None:
        raise StorageError(
            "cannot store a naive datetime -- all timestamps must be "
            "timezone-aware (STOR-6)"
        )
    return at.astimezone(UTC).isoformat()


def from_iso(text: str) -> datetime:
    """Parse a stored timestamp back into a timezone-aware UTC datetime."""
    at = datetime.fromisoformat(text)
    if at.tzinfo is None:
        raise StorageError(
            f"stored timestamp {text!r} is naive -- the database has been "
            "written to by something that did not go through this module"
        )
    return at.astimezone(UTC)

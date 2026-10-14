"""UTC datetime helpers for consistent API serialization."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC; convert aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc_z(dt: datetime) -> str:
    """Serialize as ``YYYY-MM-DDTHH:MM:SS[.fff]Z`` so JS parses as UTC."""
    aware = ensure_utc(dt)
    text = aware.isoformat()
    if text.endswith("+00:00"):
        return f"{text[:-6]}Z"
    return text

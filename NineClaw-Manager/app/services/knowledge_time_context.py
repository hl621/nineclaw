"""Cache-friendly current-time context for agent prompts."""

from __future__ import annotations

from datetime import datetime


def _format_utc_offset(current: datetime) -> str:
    offset = current.strftime("%z")
    if offset:
        return f"UTC{offset[:3]}:{offset[3:]}"
    return "local timezone"


def current_time_context(now: datetime | None = None) -> str:
    """Return current time rounded down to the hour for prompt-cache stability."""
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    current = current.replace(minute=0, second=0, microsecond=0)
    offset = _format_utc_offset(current)
    return current.strftime(f"%Y-%m-%d %H:00 {offset}")


def exact_current_time_context(
    now: datetime | None = None,
    *,
    include_seconds: bool = False,
) -> str:
    """Return exact current local time for explicit on-demand time checks."""
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    current = current.replace(microsecond=0)
    offset = _format_utc_offset(current)
    if include_seconds:
        return current.strftime(f"%Y-%m-%d %H:%M:%S {offset}")
    return current.strftime(f"%Y-%m-%d %H:%M {offset}")

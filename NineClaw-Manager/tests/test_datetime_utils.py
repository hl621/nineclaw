"""Tests for UTC datetime serialization helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.datetime_utils import format_utc_z
from app.schemas.instance import _normalize_create_job_updated_at


def test_format_utc_z_naive_assumes_utc() -> None:
    assert format_utc_z(datetime(2026, 7, 23, 8, 50, 0)) == "2026-07-23T08:50:00Z"


def test_format_utc_z_aware() -> None:
    dt = datetime(2026, 7, 23, 8, 50, 0, tzinfo=timezone.utc)
    assert format_utc_z(dt) == "2026-07-23T08:50:00Z"


def test_normalize_create_job_updated_at_appends_z() -> None:
    assert _normalize_create_job_updated_at("2026-07-23T08:50:00.123456") == (
        "2026-07-23T08:50:00.123456Z"
    )


def test_normalize_create_job_updated_at_keeps_offset() -> None:
    assert _normalize_create_job_updated_at("2026-07-23T08:50:00+00:00") == (
        "2026-07-23T08:50:00Z"
    )

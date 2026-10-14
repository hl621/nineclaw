"""Search source model – represents a configurable search endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlmodel import SQLModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SearchSource(SQLModel, table=True):
    """A configurable search source (e.g. Google, Bing, custom API)."""

    __tablename__ = "search_sources"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False, unique=True))
    description: str | None = Field(default=None, sa_column=Column(Text))

    # request_config: JSON with url, method, params, headers, body, body_type, use_proxy, proxy_url
    request_config: dict | None = Field(default=None, sa_column=Column(JSONB))

    # Python code containing an extract(html: str) -> list[dict] function
    extractor_code: str | None = Field(default=None, sa_column=Column(Text))

    # Base URL for resolving relative URLs in extracted results
    url_base: str | None = Field(default=None, sa_column=Column(String(512)))

    # Whether this source is active
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))

    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

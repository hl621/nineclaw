"""Schemas for source listing responses."""

from __future__ import annotations

from pydantic import BaseModel


class SourceSummary(BaseModel):
    source_id: str
    name: str
    description: str | None = None
    enabled: bool = True


class SourceDetail(SourceSummary):
    request_config: dict | None = None
    url_base: str | None = None

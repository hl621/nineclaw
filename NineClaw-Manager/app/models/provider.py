"""Model Provider model.

Represents an OpenAI-compatible LLM provider that can be configured by a
tenant and propagated into nineclaw containers as a custom_provider.
Mirrors the bare-minimum subset of hermes-web-ui's provider concept:
``name`` + ``base_url`` + ``api_key`` + ``models[]``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp; matches TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Provider(SQLModel, table=True):
    """LLM provider registered by a tenant."""

    __tablename__ = "providers"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    name: str = Field(max_length=128, nullable=False, index=True)
    description: str = Field(default="", max_length=1024)
    base_url: str = Field(max_length=512, nullable=False)
    # Stored in plaintext for now (single-tenant trust boundary). The API
    # never returns it back to clients — only ``has_api_key`` is exposed.
    api_key: str = Field(default="", max_length=1024)
    models: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    enabled: bool = Field(default=True)
    # ``unknown`` until the first health probe runs. Subsequent probes
    # update this in place: online | abnormal | offline.
    last_health_status: str = Field(default="unknown", max_length=16)
    last_checked_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

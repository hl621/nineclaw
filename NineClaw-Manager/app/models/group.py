"""Service Group model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp; matches TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ServiceGroup(SQLModel, table=True):
    """Service Group model representing a docker compose service group."""

    __tablename__ = "service_groups"

    id: str = Field(primary_key=True, max_length=64)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    name: str = Field(max_length=255, nullable=False)
    project_name: str = Field(max_length=255, nullable=False)
    compose_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    desired_state: str = Field(max_length=32, default="running")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

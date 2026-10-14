"""Tenant model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp; matches TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(SQLModel, table=True):
    """Tenant model representing a user/organization in the system."""

    __tablename__ = "tenants"

    id: str = Field(primary_key=True, max_length=64)
    name: str = Field(max_length=255, nullable=False)
    api_key_hash: str = Field(max_length=512, nullable=False)
    allowed_commands: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    is_active: bool = Field(default=True)

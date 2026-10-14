"""Service Template model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp; matches TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ServiceTemplate(SQLModel, table=True):
    """Service Template model defining container service configurations."""

    __tablename__ = "service_templates"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    name: str = Field(max_length=255, nullable=False)
    image: str = Field(max_length=512, nullable=False)
    ports: dict = Field(default_factory=dict, sa_column=Column(JSON))
    volumes: dict = Field(default_factory=dict, sa_column=Column(JSON))
    env_template: dict = Field(default_factory=dict, sa_column=Column(JSON))
    resource_limits: dict = Field(default_factory=dict, sa_column=Column(JSON))
    variables: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

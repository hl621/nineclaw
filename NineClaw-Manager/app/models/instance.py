"""Service Instance model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp matching the TIMESTAMP WITHOUT TIME ZONE columns
    on service_instances. Stored values are *always* UTC by convention; the
    naive form is required because asyncpg refuses to write tz-aware
    datetimes into naive Postgres columns.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ServiceInstance(SQLModel, table=True):
    """Service Instance model representing a deployed container service."""

    __tablename__ = "service_instances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_service_instances_tenant_name"),
    )

    id: str = Field(primary_key=True, max_length=64)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    template_id: UUID = Field(foreign_key="service_templates.id")
    name: str = Field(max_length=255, nullable=False)
    desired_state: str = Field(max_length=32, default="running")
    actual_state: str = Field(max_length=32, default="created")
    container_id: str | None = Field(default=None, max_length=128)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    port_mappings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    network_name: str | None = Field(default=None, max_length=255)
    group_id: str | None = Field(
        default=None, foreign_key="service_groups.id", max_length=64
    )
    error_message: str | None = Field(default=None)
    health_status: str = Field(max_length=32, default="unknown")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

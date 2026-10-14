"""Reconcile Log model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC timestamp; matches TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ReconcileLog(SQLModel, table=True):
    """Reconcile Log model tracking reconciliation operations."""

    __tablename__ = "reconcile_logs"

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    instance_id: str = Field(
        foreign_key="service_instances.id", index=True, max_length=64
    )
    action: str = Field(max_length=64, nullable=False)
    state_before: str = Field(max_length=32, nullable=False)
    state_after: str = Field(max_length=32, nullable=False)
    success: bool = Field(nullable=False)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, Text, UniqueConstraint
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WebSource(SQLModel, table=True):
    __tablename__ = "web_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_web_sources_tenant_name"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    name: str = Field(max_length=128, index=True)
    description: str = Field(default="", max_length=1024)
    type: str = Field(default="other", max_length=32)
    url: str = Field(default="", max_length=2048)
    enabled: bool = Field(default=True)
    request_config: dict | None = Field(default=None, sa_column=Column(JSON))
    extractor_code: str | None = Field(default=None, sa_column=Column(Text))
    url_base: str = Field(default="", max_length=2048)
    is_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

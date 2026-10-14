from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExternalKnowledgeConfig(SQLModel, table=True):
    """Stores knowledge backend config (one row per tenant)."""

    __tablename__ = "external_knowledge_configs"

    tenant_id: str = Field(primary_key=True, foreign_key="tenants.id", max_length=64)
    backend: str = Field(default="ragflow", max_length=32)  # ragflow | filesystem
    base_url: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=1024)
    updated_at: datetime = Field(default_factory=_utcnow)

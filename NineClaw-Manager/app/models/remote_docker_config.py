from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RemoteDockerConfig(SQLModel, table=True):
    """Stores remote Docker SSH config (one row per tenant)."""

    __tablename__ = "remote_docker_configs"

    tenant_id: str = Field(primary_key=True, foreign_key="tenants.id", max_length=64)
    enabled: bool = Field(default=False)
    ssh_host: str = Field(default="", max_length=255)
    ssh_port: int = Field(default=22)
    ssh_username: str = Field(default="", max_length=255)
    ssh_password: str = Field(default="", max_length=1024)
    updated_at: datetime = Field(default_factory=_utcnow)

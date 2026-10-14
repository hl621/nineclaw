"""MCP Server model.

Represents a Model Context Protocol server that can be registered by a
tenant and deployed into nineclaw containers. Two transport types are
supported:

- ``stdio`` — local subprocess (command + args + env)
- ``url``   — remote HTTP endpoint (url + headers)

When deployed, each entry is written into the ``mcp_servers`` block of
Hermes' config.yaml keyed by ``name``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class McpServer(SQLModel, table=True):
    """MCP server registered by a tenant."""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_mcp_servers_tenant_name"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    name: str = Field(max_length=128, nullable=False, index=True)
    description: str = Field(default="", max_length=1024)

    transport: str = Field(max_length=16, nullable=False)

    # ─── stdio fields ─────────────────────────────────────────────────────
    command: str = Field(default="", max_length=512)
    args: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    env: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))

    # ─── url fields ────────────────────────────────────────────────────────
    url: str = Field(default="", max_length=512)
    headers: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))

    # ─── per-server overrides ──────────────────────────────────────────────
    timeout: float | None = Field(default=None)
    connect_timeout: float | None = Field(default=None)

    enabled: bool = Field(default=True)

    # ─── tool management ───────────────────────────────────────────────────
    tools: list | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    tool_settings: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    tools_discovered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    tools_error: str | None = Field(
        default=None, sa_column=Column(String(1024), nullable=True)
    )

    # ─── health ────────────────────────────────────────────────────────────
    last_health_status: str = Field(default="unknown", max_length=16)
    last_checked_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
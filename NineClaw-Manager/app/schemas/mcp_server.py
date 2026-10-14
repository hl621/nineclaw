"""Pydantic schemas for the MCP Server management API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator


# ─── Request Schemas ──────────────────────────────────────────────────────────


class McpServerCreate(BaseModel):
    """Body for ``POST /mcps``."""

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    transport: str = Field(..., pattern=r"^(stdio|url)$")

    # stdio fields
    command: str = Field(default="", max_length=512)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # url fields
    url: str = Field(default="", max_length=512)
    headers: dict[str, str] = Field(default_factory=dict)

    # per-server overrides
    timeout: float | None = Field(default=None, ge=0)
    connect_timeout: float | None = Field(default=None, ge=0)

    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _check_transport_fields(self) -> "McpServerCreate":
        if self.transport == "stdio":
            if not self.command.strip():
                raise ValueError("command is required when transport=stdio")
        elif self.transport == "url":
            if not self.url.strip():
                raise ValueError("url is required when transport=url")
            try:
                HttpUrl(self.url)
            except Exception as exc:
                raise ValueError(f"invalid url: {exc}") from exc
        return self


class McpServerUpdate(BaseModel):
    """Body for ``PUT /mcps/{id}``. All fields are optional."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    transport: str | None = Field(default=None, pattern=r"^(stdio|url)$")

    command: str | None = Field(default=None, max_length=512)
    args: list[str] | None = Field(default=None)
    env: dict[str, str] | None = Field(default=None)

    url: str | None = Field(default=None, max_length=512)
    headers: dict[str, str] | None = Field(default=None)

    timeout: float | None = Field(default=None, ge=0)
    connect_timeout: float | None = Field(default=None, ge=0)

    enabled: bool | None = Field(default=None)

    @model_validator(mode="after")
    def _check_transport_fields(self) -> "McpServerUpdate":
        if self.transport == "stdio" and self.command is not None:
            if not self.command.strip():
                raise ValueError("command cannot be empty when transport=stdio")
        if self.transport == "url" and self.url is not None:
            if not self.url.strip():
                raise ValueError("url cannot be empty when transport=url")
            try:
                HttpUrl(self.url)
            except Exception as exc:
                raise ValueError(f"invalid url: {exc}") from exc
        return self


class ToolCallRequest(BaseModel):
    """Body for ``POST /mcps/{id}/call-tool``."""

    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


# ─── Response Schemas ─────────────────────────────────────────────────────────


class McpServerResponse(BaseModel):
    """MCP Server representation returned by every GET/PUT/POST."""

    id: UUID
    tenant_id: str
    name: str
    description: str
    transport: str

    command: str
    args: list[str]
    env: dict[str, str]
    url: str
    headers: dict[str, str]
    timeout: float | None
    connect_timeout: float | None

    enabled: bool
    tool_count: int = Field(
        default=0,
        description="Number of tools cached from the latest successful discovery.",
    )
    health_status: str = Field(
        default="unknown",
        description="Latest probe result: online | abnormal | offline | unknown.",
    )
    last_checked_at: datetime | None = Field(default=None)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_mcp(cls, m: Any) -> "McpServerResponse":
        return cls(
            id=m.id,
            tenant_id=m.tenant_id,
            name=m.name,
            description=m.description or "",
            transport=m.transport,
            command=m.command or "",
            args=list(m.args or []),
            env=dict(m.env or {}),
            url=m.url or "",
            headers=dict(m.headers or {}),
            timeout=m.timeout,
            connect_timeout=m.connect_timeout,
            enabled=bool(m.enabled),
            tool_count=len(m.tools or []),
            health_status=m.last_health_status or "unknown",
            last_checked_at=m.last_checked_at,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )


class ToolCallResponse(BaseModel):
    """Result of ``POST /mcps/{id}/call-tool``."""

    content: list
    is_error: bool
    duration_ms: float


# ─── Deploy ──────────────────────────────────────────────────────────────────


class ToolStateUpdate(BaseModel):
    """Body for ``PUT /mcps/{mcp_id}/tools/{tool_name}``."""

    enabled: bool


class McpToolConfig(BaseModel):
    """Per-MCP tool override for deploy."""

    mcp_id: UUID
    enabled_tools: list[str]  # list of tool names to enable for this deployment


class McpDeployRequest(BaseModel):
    """Body for ``POST /mcps/deploy``."""

    mcp_ids: list[UUID] = Field(..., min_length=1)
    instance_ids: list[str] = Field(..., min_length=1)
    tools_config: list[McpToolConfig] | None = None  # optional per-MCP tool overrides

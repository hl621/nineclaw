"""Pydantic schemas for nineclaw instance API requests and responses."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.mcp_server import McpToolConfig
from app.schemas.provider import DeployAuxModel, DeployMainModel

from app.core.config import settings
from app.core.datetime_utils import format_utc_z


# ─── Request Schemas ──────────────────────────────────────────────────────────


class InstanceCreate(BaseModel):
    """Request body for creating a new nineclaw instance."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ..., min_length=1, max_length=255, description="Human-readable instance name"
    )
    image: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Docker image reference selected from local tags, e.g. nineclaw:v2026.7.7.2",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Extra environment variables to merge with defaults",
    )
    volumes: list[str] = Field(
        default_factory=list,
        description="Extra volume binds in host:container format",
    )
    memory: str = Field(
        default_factory=lambda: settings.nineclaw_default_memory,
        description="Memory limit (e.g., '4G', '512M')",
    )
    cpus: float = Field(
        default_factory=lambda: settings.nineclaw_default_cpus,
        ge=0.1,
        le=64.0,
        description="CPU limit (e.g., 2.0 for 2 CPUs)",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Hermes dashboard config overrides (flat dot-notation, e.g. "
            "{'model': 'anthropic/claude-sonnet-4-5', 'agent.max_turns': 50}). "
            "Merged on top of NINECLAW_DEFAULT_CONFIG and pushed via "
            "PUT /api/config after the container starts."
        ),
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-instance Hermes env vars (e.g. provider API keys). "
            "Merged on top of NINECLAW_DEFAULT_ENV and pushed via "
            "PUT /api/env after the container starts."
        ),
    )
    initial_setup: "InstanceInitialSetup | None" = Field(
        default=None,
        description="Optional guided setup applied after first boot, followed by one container restart.",
    )


class InstanceInitialSetup(BaseModel):
    """Optional guided setup payload for one-shot instance creation."""

    model_config = ConfigDict(extra="forbid")

    provider_ids: list[UUID] = Field(default_factory=list)
    main_model: DeployMainModel | None = None
    auxiliary_models: list[DeployAuxModel] = Field(default_factory=list)
    skill_slugs: list[str] = Field(default_factory=list)
    mcp_ids: list[UUID] = Field(default_factory=list)
    mcp_tools_config: list[McpToolConfig] | None = None
    knowledge_ids: list[str] = Field(default_factory=list)
    web_source_ids: list[str] = Field(default_factory=list)


class InstanceUpdate(BaseModel):
    """Request body for updating an existing nineclaw instance metadata."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Human-readable instance name",
    )
    memory: str | None = Field(default=None, description="Memory limit (e.g., '4G')")
    cpus: float | None = Field(default=None, ge=0.1, le=64.0, description="CPU limit")
    environment: dict[str, str] | None = Field(
        default=None,
        description="Extra environment variables (merged with container defaults)",
    )


# ─── Response Schemas ─────────────────────────────────────────────────────────


class PortMapping(BaseModel):
    """A single port mapping entry."""

    host_port: int = Field(..., description="Host-side port number")
    container_port: int = Field(..., description="Container-side port number")


def _coerce_port_mappings(raw: Any) -> dict[str, PortMapping]:
    """Convert a raw port_mappings dict (from JSON column) into typed values."""
    if not raw:
        return {}
    coerced: dict[str, PortMapping] = {}
    for key, val in raw.items():
        coerced[key] = PortMapping(**val) if isinstance(val, dict) else val
    return coerced


class InstanceResponse(BaseModel):
    """Minimal instance representation returned in list and action responses."""

    id: str = Field(..., description="Unique instance ID")
    name: str = Field(..., description="Instance name")
    tenant_id: str = Field(..., description="Owning tenant ID")
    desired_state: str = Field(
        ..., description="Desired state: running, stopped, restarting, removed"
    )
    actual_state: str = Field(
        ..., description="Actual container state reported by Docker"
    )
    container_id: str | None = Field(None, description="Docker container ID")
    port_mappings: dict[str, PortMapping] = Field(
        default_factory=dict,
        description="Port mappings keyed by service name (gateway, webui, dashboard)",
    )
    create_job: dict[str, Any] | None = Field(
        default=None,
        description="Safe summary of the active or last create job.",
    )
    image: str | None = Field(
        default=None,
        description="Container image reference stored in instance config.",
    )
    created_at: datetime = Field(..., description="Instance creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC)")

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def _serialize_utc_timestamps(self, value: datetime) -> str:
        return format_utc_z(value)

    @classmethod
    def from_orm_instance(cls, instance: Any) -> "InstanceResponse":
        """Build from a ServiceInstance ORM object."""
        return cls(
            id=instance.id,
            name=instance.name,
            tenant_id=instance.tenant_id,
            desired_state=instance.desired_state,
            actual_state=instance.actual_state,
            container_id=instance.container_id,
            port_mappings=_coerce_port_mappings(instance.port_mappings),
            create_job=_safe_create_job(instance.config),
            image=_resolve_instance_image(instance.config),
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )


class InstanceDetail(InstanceResponse):
    """Full instance details including config, network, and health."""

    config: dict[str, Any] = Field(
        default_factory=dict, description="Rendered container configuration"
    )
    network_name: str | None = Field(
        None, description="Docker network the container is attached to"
    )
    health_status: str = Field(
        "unknown", description="Health status: healthy, unhealthy, unknown"
    )
    error_message: str | None = Field(None, description="Last error message if any")

    @classmethod
    def from_orm_instance(cls, instance: Any) -> "InstanceDetail":
        """Build from a ServiceInstance ORM object."""
        return cls(
            id=instance.id,
            name=instance.name,
            tenant_id=instance.tenant_id,
            desired_state=instance.desired_state,
            actual_state=instance.actual_state,
            container_id=instance.container_id,
            port_mappings=_coerce_port_mappings(instance.port_mappings),
            create_job=_safe_create_job(instance.config),
            image=_resolve_instance_image(instance.config),
            created_at=instance.created_at,
            config=_safe_instance_config(instance.config),
            network_name=instance.network_name,
            health_status=instance.health_status or "unknown",
            error_message=instance.error_message,
            updated_at=instance.updated_at,
        )


def _safe_instance_config(config: Any) -> dict[str, Any]:
    """Project container metadata without exposing Manager or provider secrets."""
    if not isinstance(config, dict):
        return {}
    result = deepcopy(config)
    environment = result.get("environment")
    if not isinstance(environment, dict):
        return result
    safe_environment: dict[str, Any] = {}
    for key, value in environment.items():
        normalized = str(key).upper()
        if normalized == "NINECLAW_MANAGER_URL" or normalized.startswith(
            "NINECLAW_WORKSPACE_"
        ):
            continue
        if any(
            marker in normalized
            for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")
        ):
            safe_environment[str(key)] = "[REDACTED]"
        else:
            safe_environment[str(key)] = value
    result["environment"] = safe_environment
    return result


def _safe_create_job(config: Any) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    raw = config.get("create_job")
    if not isinstance(raw, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("job_id", "stage", "status", "error", "updated_at"):
        value = raw.get(key)
        if value is None:
            continue
        if key == "updated_at" and isinstance(value, str):
            result[key] = _normalize_create_job_updated_at(value)
        else:
            result[key] = value
    return result or None


def _normalize_create_job_updated_at(value: str) -> str:
    """Ensure create_job timestamps are explicit UTC so browsers don't treat them as local."""
    text = value.strip()
    if not text:
        return text
    if text.endswith("Z") or "+" in text[10:] or text.endswith("-00:00"):
        return text.replace("+00:00", "Z")
    # Naive ISO from ``datetime.isoformat()`` on UTC-naive values.
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    return format_utc_z(dt)


def _resolve_instance_image(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    image = config.get("image")
    if isinstance(image, str) and image.strip():
        return image.strip()
    return None

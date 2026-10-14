"""Pydantic schemas for the Provider (LLM) management API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _normalize_models(value: Any) -> list[str]:
    """Coerce input into a clean ``list[str]`` of model identifiers.

    Accepts list/tuple of strings or a newline/comma separated string. Strips
    whitespace, drops empty entries, preserves order while removing dupes.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw = [chunk for line in value.splitlines() for chunk in line.split(",")]
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raise ValueError("models must be a list of strings")

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("models entries must be strings")
        s = item.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    return cleaned


# ─── Request Schemas ──────────────────────────────────────────────────────────


class ProviderCreate(BaseModel):
    """Body for ``POST /providers``."""

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(default="", max_length=1024)
    models: list[str] = Field(default_factory=list)
    enabled: bool = Field(default=True)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("base_url is required")
        # Accept anything HttpUrl would accept; we tolerate trailing slashes.
        try:
            HttpUrl(v)
        except Exception as exc:  # noqa: BLE001 — narrow to ValueError downstream
            raise ValueError(f"invalid base_url: {exc}") from exc
        return v.rstrip("/")

    @field_validator("models", mode="before")
    @classmethod
    def _coerce_models(cls, v: Any) -> list[str]:
        return _normalize_models(v)


class ProviderUpdate(BaseModel):
    """Body for ``PUT /providers/{id}``. All fields are optional.

    A missing or ``None`` ``api_key`` leaves the stored secret untouched. An
    explicit empty string clears it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=1024)
    models: list[str] | None = Field(default=None)
    enabled: bool | None = Field(default=None)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("base_url cannot be empty")
        try:
            HttpUrl(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"invalid base_url: {exc}") from exc
        return v.rstrip("/")

    @field_validator("models", mode="before")
    @classmethod
    def _coerce_models(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        return _normalize_models(v)


# ─── Response Schemas ─────────────────────────────────────────────────────────


class ProviderResponse(BaseModel):
    """Provider representation returned by every GET/PUT/POST."""

    id: UUID
    tenant_id: str
    name: str
    description: str
    base_url: str
    has_api_key: bool = Field(
        description="True if an API key is stored. The actual secret is never returned."
    )
    models: list[str]
    enabled: bool
    health_status: str = Field(
        default="unknown",
        description="Latest probe result: online | abnormal | offline | unknown.",
    )
    last_checked_at: datetime | None = Field(default=None)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_provider(cls, p: Any) -> "ProviderResponse":
        return cls(
            id=p.id,
            tenant_id=p.tenant_id,
            name=p.name,
            description=p.description or "",
            base_url=p.base_url,
            has_api_key=bool(p.api_key),
            models=list(p.models or []),
            enabled=bool(p.enabled),
            health_status=p.last_health_status or "unknown",
            last_checked_at=p.last_checked_at,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )


# ─── Discovery (proxy /v1/models) ─────────────────────────────────────────────


class FetchModelsRequest(BaseModel):
    """Body for ``POST /providers/fetch-models``.

    Either ``api_key`` or ``provider_id`` must resolve to a usable secret.
    Empty ``api_key`` plus a ``provider_id`` belonging to the caller's
    tenant means "use the stored key for that provider".
    """

    base_url: str = Field(..., min_length=1, max_length=512)
    api_key: str = Field(default="", max_length=1024)
    provider_id: UUID | None = Field(default=None)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("base_url is required")
        try:
            HttpUrl(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"invalid base_url: {exc}") from exc
        return v.rstrip("/")


class FetchModelsResponse(BaseModel):
    """Body returned from ``POST /providers/fetch-models``."""

    models: list[str]
    total: int
    upstream_url: str = Field(
        description="The actual URL that was queried; useful for debugging.",
    )


# ─── Chat comparison ─────────────────────────────────────────────────────────


class ProviderChatImageUrl(BaseModel):
    """OpenAI vision ``image_url`` payload (HTTP URL or data URL)."""

    url: str = Field(..., min_length=1)
    detail: str | None = Field(default=None, max_length=16)


class ProviderChatContentPart(BaseModel):
    """One multimodal content part (text or image)."""

    type: str = Field(..., min_length=1, max_length=32)
    text: str | None = None
    image_url: ProviderChatImageUrl | None = None


class ProviderChatMessage(BaseModel):
    """Single OpenAI-compatible chat message.

    ``content`` may be a plain string (LLM) or a list of parts (VLM / vision).
    """

    role: str = Field(..., min_length=1, max_length=32)
    content: str | list[ProviderChatContentPart] = Field(...)

    @field_validator("content")
    @classmethod
    def _content_not_empty(cls, value: str | list[ProviderChatContentPart]):
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("content must not be empty")
            return value
        if not value:
            raise ValueError("content parts must not be empty")
        return value


class ProviderChatCompletionRequest(BaseModel):
    """Body for ``POST /providers/chat/completions``."""

    provider_id: UUID
    model: str = Field(..., min_length=1, max_length=256)
    messages: list[ProviderChatMessage] = Field(..., min_length=1)
    stream: bool = Field(default=True)


class ProviderEmbeddingRequest(BaseModel):
    """Body for ``POST /providers/embeddings`` (OpenAI-compatible embeddings)."""

    provider_id: UUID
    model: str = Field(..., min_length=1, max_length=256)
    input: str | list[str] = Field(..., description="Text or list of texts to embed")
    encoding_format: str | None = Field(default="float", max_length=16)
    dimensions: int | None = Field(default=None, ge=1, le=8192)


class ProviderRerankRequest(BaseModel):
    """Body for ``POST /providers/rerank`` (OpenAI / Jina-style rerank)."""

    provider_id: UUID
    model: str = Field(..., min_length=1, max_length=256)
    query: str = Field(..., min_length=1)
    documents: list[str] = Field(..., min_length=1)
    top_n: int | None = Field(default=None, ge=1, le=100)


class ProviderSpeechRequest(BaseModel):
    """Body for ``POST /providers/audio/speech`` (OpenAI-compatible TTS)."""

    provider_id: UUID
    model: str = Field(..., min_length=1, max_length=256)
    input: str = Field(..., min_length=1, max_length=4096)
    voice: str | None = Field(default=None, max_length=128)
    response_format: str = Field(default="mp3", max_length=16)
    speed: float | None = Field(default=None, ge=0.25, le=4.0)


# ─── Deploy ──────────────────────────────────────────────────────────────────


class DeployMainModel(BaseModel):
    """The main model selection for ``POST /providers/deploy``.

    ``provider`` matches the ``name`` we will write into the new
    ``custom_providers[].name`` entries — i.e. the NineClaw-WebUI
    Provider.name. ``model`` is the model id (one of that provider's
    models). The wizard's step 3 picker is constrained to (provider, model)
    pairs drawn from the providers selected in step 1.
    """

    provider: str = Field(..., min_length=1, max_length=128)
    model: str = Field(..., min_length=1, max_length=256)


class DeployAuxModel(BaseModel):
    """An auxiliary task assignment to push via ``/api/model/set``.

    ``task`` is one of hermes' auxiliary task names (``vision``,
    ``web_extract``, ``compression`` etc). The deploy step calls
    ``set_model_assignment(scope="auxiliary", task=task, provider, model)``
    once per entry. Tasks the user leaves at "跟随主模型" are simply
    omitted from this list so hermes' existing assignment is left alone.
    """

    task: str = Field(..., min_length=1, max_length=64)
    provider: str = Field(..., min_length=1, max_length=128)
    model: str = Field(..., max_length=256)


class DeployRequest(BaseModel):
    """Body for ``POST /providers/deploy``."""

    provider_ids: list[UUID] = Field(...)
    instance_ids: list[str] = Field(..., min_length=1)
    main_model: DeployMainModel | None = Field(
        default=None,
        description=(
            "Main model to write into config.model. Optional: when null the "
            "deployment only refreshes custom_providers and leaves the "
            "instance's existing main model selection alone."
        ),
    )
    auxiliary_models: list[DeployAuxModel] = Field(
        default_factory=list,
        description=(
            "Optional auxiliary task assignments. Each entry triggers one "
            "/api/model/set call with scope='auxiliary'. Empty list keeps "
            "hermes' existing assignments untouched."
        ),
    )

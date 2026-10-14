"""Schemas for knowledge studio (RAG Q&A chat) — aligned with skill studio."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeStudioCreateSessionRequest(BaseModel):
    category: str | None = None


class KnowledgeStudioCreateSessionResponse(BaseModel):
    session_id: str
    kb_id: str
    category: str | None = None


class KnowledgeStudioQaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    message: str | None = None
    resume_run_id: str | None = None
    from_index: int | None = Field(
        default=None,
        ge=0,
        description="Optional event index to resume SSE delivery from.",
    )
    top_k: int = Field(default=5, ge=1, le=50)
    rerank_id: str | None = None
    tenant_rerank_id: str | int | None = None
    temperature: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Optional sampling temperature. Omit to use the model/provider default.",
    )
    enable_thinking: bool | None = Field(
        default=None,
        description="Optional thinking switch for providers/models that support enable_thinking. Omit to use the model/provider default.",
    )
    provider_id: str | None = Field(
        default=None,
        description="Optional LLM provider id from model management.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model name; must belong to provider_id when set.",
    )
    cross_languages: list[str] | None = Field(
        default=None,
        description="跨语言检索目标语言列表，作为 cross_languages 传给 RAGFlow。",
    )

    @field_validator("provider_id", "model", "rerank_id", "tenant_rerank_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("cross_languages", mode="before")
    @classmethod
    def _clean_cross_languages(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or None
        return value


class KnowledgeStudioCancelRequest(BaseModel):
    run_id: str
    session_id: str

"""Schemas for the skill studio (file browser + LLM chat) APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SkillStudioFileEntry(BaseModel):
    path: str = Field(description="Relative path within the skill folder.")
    name: str
    type: str = Field(description="'file' or 'folder'")
    size_bytes: int = 0
    updated_at: datetime | None = None


class SkillStudioFileListResponse(BaseModel):
    slug: str
    files: list[SkillStudioFileEntry]


class SkillStudioFileContentResponse(BaseModel):
    slug: str
    path: str
    content: str
    is_binary: bool = False
    size_bytes: int = 0
    updated_at: datetime | None = None


class SkillStudioSaveFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""


class SkillStudioDeleteFileRequest(BaseModel):
    path: str = Field(..., min_length=1)


class SkillStudioMoveFileRequest(BaseModel):
    src: str = Field(..., min_length=1)
    dest: str = Field(..., min_length=1)


class SkillStudioCreateSessionRequest(BaseModel):
    category: str | None = None


class SkillStudioCreateSessionResponse(BaseModel):
    session_id: str
    category: str | None = None


class SkillStudioChatRequest(BaseModel):
    session_id: str
    message: str | None = None
    category: str | None = None
    resume_run_id: str | None = None
    from_index: int | None = Field(
        default=None,
        ge=0,
        description="Optional event index to resume SSE delivery from.",
    )
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


class SkillStudioQaRequest(BaseModel):
    session_id: str
    message: str | None = None
    resume_run_id: str | None = None
    from_index: int | None = Field(
        default=None,
        ge=0,
        description="Optional event index to resume SSE delivery from.",
    )
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


class SkillStudioCancelRequest(BaseModel):
    run_id: str
    session_id: str

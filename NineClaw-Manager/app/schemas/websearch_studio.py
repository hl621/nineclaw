"""Schemas for the WebSearch extractor agent."""

from pydantic import BaseModel, Field


class WebSearchStudioSessionResponse(BaseModel):
    session_id: str


class WebSearchStudioChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)
    provider_id: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    enable_thinking: bool | None = None


class WebSearchStudioCancelRequest(BaseModel):
    session_id: str
    run_id: str

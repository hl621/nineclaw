"""Schemas for lightweight exploration endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ColumnRecognitionRequest(BaseModel):
    """Describe a page whose repeated link blocks should be inspected."""

    source_id: str
    query: str = ""
    limit: int = Field(default=7, ge=1)
    min_link_count: int = Field(
        default=6,
        ge=1,
        description="同一链接组完成 URL 和标题过滤后的最小链接数。",
    )


class ColumnSample(BaseModel):
    block_xpath: str
    link_xpath: str
    link_total: int
    link_titles: list[str]


class ColumnRecognitionResponse(BaseModel):
    source_id: str
    query: str
    desc_for_ai: str
    link_blocks: list[ColumnSample] = Field(default_factory=list)
    error: str | None = None


class LinkGrepRequest(BaseModel):
    """Search complete anchor text in a source's saved HTML."""

    source_id: str
    pattern: str = Field(min_length=1)
    ignore_case: bool = True
    limit: int = Field(default=7, ge=1)


class LinkGrepResponse(BaseModel):
    source_id: str
    pattern: str
    ignore_case: bool
    desc_for_ai: str
    link_blocks: list[ColumnSample] = Field(default_factory=list)
    error: str | None = None


class DOMTreeRequest(BaseModel):
    source_id: str
    block_xpath: str


class DOMTreeResponse(BaseModel):
    source_id: str
    block_xpath: str
    desc_for_ai: str
    dom_tree: str | None = None
    error: str | None = None

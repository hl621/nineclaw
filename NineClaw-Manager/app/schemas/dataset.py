"""RAGFlow-compatible dataset (knowledge base) API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParseDocumentsRequest(BaseModel):
    """Body for ``POST /v1/datasets/{dataset_id}/chunks``."""

    document_ids: list[str] = Field(
        default_factory=list,
        description="要解析的文档 ID 列表（知识库内文件 id）",
    )

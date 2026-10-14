"""Pydantic schemas for the file-based Knowledge (RAG) registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KnowledgeStatus = Literal[
    "pending",
    "building",
    "success",
    "part_success",
    "fail",
]
KnowledgePermission = Literal["me", "team"]
ChunkMethod = Literal[
    "naive",
    "book",
    "email",
    "laws",
    "manual",
    "one",
    "paper",
    "picture",
    "presentation",
    "qa",
    "table",
    "tag",
]


class KnowledgeFileResponse(BaseModel):
    id: str = Field(description="Stored filename on disk (includes upload prefix).")
    name: str = Field(description="Display name; duplicates get (1), (2), … suffix.")
    size_bytes: int = Field(default=0)
    parsed: bool = Field(default=False)
    parse_failed: bool = Field(
        default=False, description="True when RAGFlow reports FAIL run status."
    )
    chunk_count: int = Field(
        default=0,
        description="Number of vector chunks indexed by RAGFlow (chunk_num field).",
    )
    progress: float | None = Field(
        default=None,
        description="Document parsing progress reported by RAGFlow.",
    )
    progress_msg: str | None = Field(
        default=None,
        description="RAGFlow parsing progress detail, including failure reason.",
    )
    preview: str | None = Field(default=None)
    uploaded_at: datetime | None = Field(
        default=None, description="Upload time (mtime), ascending in file list."
    )


class KnowledgeResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    group: str = ""
    owner: str = ""
    serial: str | None = None
    status: KnowledgeStatus = "pending"
    doc_count: int = 0
    updated_at: datetime
    avatar: str | None = None
    embedding_model: str | None = None
    chunk_method: str | None = None
    permission: str | None = None
    parser_config: dict[str, Any] | None = None


class KnowledgeDetailResponse(KnowledgeResponse):
    files: list[KnowledgeFileResponse] = Field(default_factory=list)


class KnowledgeFileListResponse(BaseModel):
    items: list[KnowledgeFileResponse] = Field(default_factory=list)
    total: int = 0


class CreateKnowledgeRequest(BaseModel):
    """Body for ``POST /v1/knowledge`` — all fields stored locally on disk."""

    name: str = Field(..., min_length=1, max_length=128)
    avatar: str | None = None
    description: str | None = None
    embedding_model: str | None = None
    permission: KnowledgePermission = "me"
    chunk_method: ChunkMethod | None = "naive"
    parser_config: dict[str, Any] | None = None
    parse_type: int | None = None
    pipeline_id: str | None = None
    group: str = ""
    owner: str = ""
    serial: str | None = None
    id: str | None = Field(
        default=None,
        description="Optional slug; derived from name when omitted.",
    )

    @model_validator(mode="after")
    def validate_ingestion_mode(self) -> CreateKnowledgeRequest:
        uses_pipeline = self.parse_type is not None or self.pipeline_id is not None
        if uses_pipeline:
            if self.parse_type is None or not self.pipeline_id:
                raise ValueError(
                    "使用 pipeline 时必须同时提供 parse_type 与 pipeline_id"
                )
            if self.chunk_method is not None or self.parser_config is not None:
                raise ValueError(
                    "指定 pipeline 时不能同时传 chunk_method 或 parser_config"
                )
        return self


class UpdateKnowledgeRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    group: str | None = None
    owner: str | None = None
    serial: str | None = None
    status: KnowledgeStatus | None = None
    avatar: str | None = None
    embedding_model: str | None = None
    chunk_method: str | None = None
    permission: str | None = None
    parser_config: dict[str, Any] | None = None


class KnowledgeQARequest(BaseModel):
    """知识问答（SSE）请求体，dataset_ids 即知识库 ID 列表。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    dataset_ids: list[str] = Field(
        ...,
        min_length=1,
        description="知识库 ID 列表，对应 /v1/knowledge 下的 id",
    )
    top_k: int = Field(default=5, ge=1, le=50)
    rerank_id: str | None = None
    tenant_rerank_id: str | int | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    enable_thinking: bool | None = None
    provider_id: str | None = Field(
        default=None,
        description="LLM Provider ID；省略则自动选用已启用的 Provider",
    )
    model: str | None = Field(
        default=None,
        description="模型 ID；省略则使用该 Provider 的第一个模型",
    )

    @field_validator("provider_id", "model", "rerank_id", "tenant_rerank_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class QaReference(BaseModel):
    dataset_id: str
    file_id: str | None = None
    file_name: str | None = None
    chunk_id: str | None = None
    text: str | None = None
    score: float | None = None
    available: bool | None = True


class QaResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1)
    similarity: float = Field(default=0.34, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class RecallChunk(BaseModel):
    chunk_id: str
    text: str
    score: float
    file_name: str | None = None


class RecallResponse(BaseModel):
    chunks: list[RecallChunk] = Field(default_factory=list)


class KnowledgeFileChunkResponse(BaseModel):
    id: str
    content: str
    available: bool = True
    important_keywords: list[str] = Field(default_factory=list)
    image_id: str = ""
    synthetic: bool = False


class KnowledgeFileChunkListResponse(BaseModel):
    chunks: list[KnowledgeFileChunkResponse] = Field(default_factory=list)
    total: int = 0
    synthetic: bool = False


class UpdateKnowledgeChunkRequest(BaseModel):
    available: bool = Field(description="true=启用参与检索，false=停用")


class SwitchKnowledgeChunksRequest(BaseModel):
    chunk_ids: list[str] = Field(
        ..., min_length=1, description="要切换状态的切片 ID 列表"
    )
    available: bool = Field(description="true=批量启用，false=批量停用")


# ─── Deploy ───────────────────────────────────────────────────────────────────


class KnowledgeDeployRequest(BaseModel):
    """Body for ``POST /v1/knowledge/deploy`` — push knowledge config to instances via SSE."""

    knowledge_ids: list[str] = Field(
        ..., min_length=1, description="要部署的知识库 ID 列表"
    )
    instance_ids: list[str] = Field(
        ..., min_length=1, description="目标 NineClaw 实例 ID 列表"
    )
    knowledge_names: dict[str, str] | None = Field(
        default=None,
        description="可选：知识库 ID → 显示名称；优先于服务端查询结果写入 QYRAG_DATASETS",
    )

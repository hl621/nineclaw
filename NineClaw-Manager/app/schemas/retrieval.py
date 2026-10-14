"""RAGFlow-compatible retrieval (检索测试) schemas.

Reference: https://ragflow.io/docs/http_api_reference#retrieve-chunks
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _clean_string_list(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None
    return value


class MetadataConditionItem(BaseModel):
    name: str
    comparison_operator: str = Field(
        description='e.g. "=", "contains", "not contains", "start with", "empty", "not empty"'
    )
    value: str = ""


class MetadataCondition(BaseModel):
    logic: Literal["and", "or"] = "and"
    conditions: list[MetadataConditionItem] = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    """Body for ``POST /v1/knowledge/retrieval`` (RAGFlow-compatible)."""

    question: str = Field(..., min_length=1, description="用户查询或关键词")
    dataset_ids: list[str] = Field(
        default_factory=list,
        description="知识库 ID 列表（对应 RAGFlow dataset_ids）",
    )
    document_ids: list[str] = Field(
        default_factory=list,
        description="文档 ID 列表（对应知识库内文件 id）",
    )
    page: int = Field(default=1, ge=1, description="结果页码")
    page_size: int = Field(default=30, ge=1, le=100, description="每页 chunk 数")
    similarity_threshold: float = Field(
        default=0.2, ge=0.0, le=1.0, description="最低相似度阈值"
    )
    vector_similarity_weight: float = Field(
        default=0.3, ge=0.0, le=1.0, description="向量相似度权重"
    )
    top_k: int = Field(
        default=1024, ge=1, le=10_000, description="参与相似度计算的 chunk 上限"
    )
    rerank_id: str | None = None
    tenant_rerank_id: str | int | None = None
    keyword: bool = Field(default=False, description="是否启用关键词匹配")
    highlight: bool = Field(default=False, description="是否高亮匹配词")
    cross_languages: list[str] | None = None
    metadata_condition: MetadataCondition | None = None
    use_kg: bool = False

    @field_validator("rerank_id", "tenant_rerank_id", mode="before")
    @classmethod
    def _blank_rerank_to_none(cls, value):
        return _blank_to_none(value)

    @field_validator("cross_languages", mode="before")
    @classmethod
    def _clean_cross_languages(cls, value):
        return _clean_string_list(value)

    @model_validator(mode="after")
    def require_search_scope(self) -> RetrievalRequest:
        if not self.dataset_ids and not self.document_ids:
            raise ValueError("dataset_ids 或 document_ids 至少提供一个")
        return self


class RetrievalKbRequest(BaseModel):
    """``POST /v1/knowledge/{kb_id}/retrieval`` — dataset_ids 由路径注入。"""

    question: str = Field(..., min_length=1)
    document_ids: list[str] = Field(default_factory=list)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)
    similarity_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    vector_similarity_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    top_k: int = Field(default=1024, ge=1, le=10_000)
    rerank_id: str | None = None
    tenant_rerank_id: str | int | None = None
    keyword: bool = False
    highlight: bool = False
    cross_languages: list[str] | None = None
    metadata_condition: MetadataCondition | None = None
    use_kg: bool = False

    @field_validator("rerank_id", "tenant_rerank_id", mode="before")
    @classmethod
    def _blank_rerank_to_none(cls, value):
        return _blank_to_none(value)

    @field_validator("cross_languages", mode="before")
    @classmethod
    def _clean_cross_languages(cls, value):
        return _clean_string_list(value)

    def to_retrieval_request(self, kb_id: str) -> RetrievalRequest:
        return RetrievalRequest(
            question=self.question,
            dataset_ids=[kb_id],
            document_ids=self.document_ids,
            page=self.page,
            page_size=self.page_size,
            similarity_threshold=self.similarity_threshold,
            vector_similarity_weight=self.vector_similarity_weight,
            top_k=self.top_k,
            rerank_id=self.rerank_id,
            tenant_rerank_id=self.tenant_rerank_id,
            keyword=self.keyword,
            highlight=self.highlight,
            cross_languages=self.cross_languages,
            metadata_condition=self.metadata_condition,
            use_kg=self.use_kg,
        )


class RetrievalChunkResponse(BaseModel):
    """Single chunk in RAGFlow retrieval response."""

    id: str
    content: str
    content_ltks: str = ""
    document_id: str
    document_keyword: str = ""
    highlight: str | None = None
    image_id: str = ""
    important_keywords: list[str] = Field(default_factory=list)
    tag_kwd: list[str] = Field(default_factory=list)
    kb_id: str
    positions: list[str] = Field(default_factory=list)
    similarity: float
    term_similarity: float
    vector_similarity: float
    rerank_score: float | None = None
    available: bool = True


class DocAggResponse(BaseModel):
    doc_id: str
    doc_name: str
    count: int


class RetrievalDataResponse(BaseModel):
    chunks: list[RetrievalChunkResponse] = Field(default_factory=list)
    doc_aggs: list[DocAggResponse] = Field(default_factory=list)
    total: int = 0
    rerank_applied: bool = False
    rerank_warning: str | None = None


class RetrievalResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: RetrievalDataResponse

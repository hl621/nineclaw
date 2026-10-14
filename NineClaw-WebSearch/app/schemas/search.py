"""Schemas for search and extract endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceHit(BaseModel):
    source_id: str
    source_name: str
    rank: int
    title: str = ""
    url: str = ""
    desc: str | None = None


class SearchResult(BaseModel):
    url: str
    title: str
    desc: str | None = None
    score: float = 0.0
    sources: list[SourceHit] = []


class SearchRequest(BaseModel):
    query: str
    tags: list[str] | None = None             # filter by tags first; None = no tag filter
    include_sources: list[str] | None = None  # source_id list; None = all enabled
    exclude_sources: list[str] = []           # source_id list to skip
    limit: int = 20                           # max results to return
    request_timeout_ms: int = 10000           # HTTP request timeout per source
    parse_timeout_ms: int = 5000              # extract() execution timeout per source
    merge_result: bool = True                 # True: dedup by URL; False: show all
    proxy_pool: list[str] = []                # global proxy pool, rotated per source
    cover_default_proxy: bool = False         # True = proxy_pool overrides source-level proxy config
    cover_default_weight: dict[str, float] = Field(default_factory=dict, json_schema_extra={"example": {}})


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    stats: list["SourceStats"] = []


class WeightedSource(BaseModel):
    source_id: str
    weight: float = Field(ge=0.0, le=1.0)


class TestScoreRequest(BaseModel):
    sources: list[WeightedSource]
    results: list[SearchResult]
    limit: int = 20


class SourceStats(BaseModel):
    source_id: str
    source_name: str
    status: str  # "ok" | "timeout" | "error"
    result_count: int
    request_time_ms: int
    parse_time_ms: int
    weight: float
    error: str | None = None


class ExtractRequest(BaseModel):
    urls: list[str]
    proxies: list[str] = []  # optional; rotated as a pool if multiple given


class ExtractedContent(BaseModel):
    url: str
    title: str | None = None
    content: str | None = None
    content_xpath: str | None = None
    publish_date: str | None = None
    error: str | None = None


class ExtractResponse(BaseModel):
    results: list[ExtractedContent]


class LinkItem(BaseModel):
    url: str | None = None
    title: str | None = None


class LinkBlock(BaseModel):
    link_xpath: str
    block_xpath: str
    link_items: list[LinkItem]


class ExtractedListLink(BaseModel):
    url: str
    link_blocks: list[LinkBlock] | None = None
    error: str | None = None


class ExtractListLinkResponse(BaseModel):
    results: list[ExtractedListLink]

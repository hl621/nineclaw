"""Search and extract routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.search import (
    ExtractRequest,
    ExtractResponse,
    ExtractListLinkResponse,
    SearchRequest,
    SearchResponse,
    TestScoreRequest,
)
from app.services.search_service import do_search
from app.services.search_service import rank_results
from app.services.extract_service import do_extract, do_extract_listlink

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest):
    return await do_search(body)


@router.post("/search/test_score", response_model=SearchResponse)
async def test_score(body: TestScoreRequest):
    """Re-score existing search results with explicit per-source weights."""
    weights = {source.source_id: source.weight for source in body.sources}
    return SearchResponse(query="", results=rank_results(body.results, weights)[:body.limit], stats=[])


@router.post("/extract_detail", response_model=ExtractResponse)
async def extract_detail(body: ExtractRequest):
    return await do_extract(
        body,
        max_urls=settings.extract_max_urls,
        concurrency=settings.extract_concurrency,
    )


@router.post("/extract_listlink", response_model=ExtractListLinkResponse)
async def extract_listlink(body: ExtractRequest):
    return await do_extract_listlink(
        body,
        max_urls=settings.extract_max_urls,
        concurrency=settings.extract_concurrency,
    )

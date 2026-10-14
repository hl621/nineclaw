"""Endpoints intended for model-assisted website exploration."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.explore import (
    ColumnRecognitionRequest,
    ColumnRecognitionResponse,
    DOMTreeRequest,
    DOMTreeResponse,
    LinkGrepRequest,
    LinkGrepResponse,
)
from app.services.explore_service import (
    extract_dom_tree,
    grep_source_links,
    recognize_columns,
)

router = APIRouter(prefix="/sources", tags=["explore"])


@router.post(
    "/explore/listlink",
    response_model=ColumnRecognitionResponse,
    summary="识别页面栏目",
)
async def recognize_page_columns(
    body: ColumnRecognitionRequest,
) -> ColumnRecognitionResponse:
    """Recognize repeated link columns and return compact link titles."""
    return await recognize_columns(body)


@router.post(
    "/explore/greplink",
    response_model=LinkGrepResponse,
    summary="用正则搜索链接的完整文本",
)
async def grep_links(body: LinkGrepRequest) -> LinkGrepResponse:
    """Search string(a) and return matching link and block XPath values."""
    return await grep_source_links(body)


@router.post(
    "/explore/domtree",
    response_model=DOMTreeResponse,
    summary="通过 block_xpath 观察局部 DOM 结构",
)
async def inspect_dom_tree(body: DOMTreeRequest) -> DOMTreeResponse:
    return await extract_dom_tree(body)

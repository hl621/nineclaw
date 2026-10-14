"""Extract service – fetches URLs and extracts main content via html_extractor."""

from __future__ import annotations

import asyncio
import itertools
import logging

import httpx
from fastapi import HTTPException

from app.schemas.search import (
    ExtractRequest, ExtractResponse, ExtractedContent,
    ExtractListLinkResponse, ExtractedListLink, LinkBlock, LinkItem,
)
from app.utils.html_extractor import extract_info_from_html, parser_linkblock

logger = logging.getLogger(__name__)


async def _extract_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str
) -> ExtractedContent:
    async with sem:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            info = extract_info_from_html(resp.text, url=url)
            return ExtractedContent(
                url=url,
                title=info.title,
                content=info.content.content_text if info.content else None,
                content_xpath=info.content.content_xpath if info.content else None,
                publish_date=(
                    info.publish_date.datetime.isoformat() if info.publish_date else None
                ),
            )
        except Exception as e:
            logger.exception("Failed to extract %s", url)
            return ExtractedContent(url=url, error=str(e))


async def do_extract(
    req: ExtractRequest, max_urls: int, concurrency: int
) -> ExtractResponse:
    """Concurrently fetch & extract URLs, bounded by a semaphore pool."""
    if len(req.urls) > max_urls:
        raise HTTPException(
            status_code=400,
            detail=f"Too many URLs: {len(req.urls)} (max {max_urls})",
        )

    sem = asyncio.Semaphore(concurrency)
    proxies = req.proxies or [None]  # None => direct connection
    # One reusable client per distinct proxy, rotated across URLs.
    clients = {
        p: httpx.AsyncClient(timeout=30, follow_redirects=True, proxies=p)
        for p in set(proxies)
    }
    pool = itertools.cycle(proxies)
    try:
        results = await asyncio.gather(
            *(_extract_one(clients[next(pool)], sem, url) for url in req.urls)
        )
    finally:
        await asyncio.gather(*(c.aclose() for c in clients.values()))
    return ExtractResponse(results=list(results))


async def _extract_listlink_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str
) -> ExtractedListLink:
    async with sem:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            blocks = parser_linkblock(resp.text, url_base=url)
            return ExtractedListLink(
                url=url,
                link_blocks=[
                    LinkBlock(
                        link_xpath=b.link_xpath,
                        block_xpath=b.block_xpath,
                        link_items=[LinkItem(url=i.url, title=i.title) for i in b.link_items],
                    )
                    for b in blocks
                ],
            )
        except Exception as e:
            logger.exception("Failed to extract listlink %s", url)
            return ExtractedListLink(url=url, error=str(e))


async def do_extract_listlink(
    req: ExtractRequest, max_urls: int, concurrency: int
) -> ExtractListLinkResponse:
    if len(req.urls) > max_urls:
        raise HTTPException(
            status_code=400,
            detail=f"Too many URLs: {len(req.urls)} (max {max_urls})",
        )
    sem = asyncio.Semaphore(concurrency)
    proxies = req.proxies or [None]
    clients = {
        p: httpx.AsyncClient(timeout=30, follow_redirects=True, proxies=p)
        for p in set(proxies)
    }
    pool = itertools.cycle(proxies)
    try:
        results = await asyncio.gather(
            *(_extract_listlink_one(clients[next(pool)], sem, url) for url in req.urls)
        )
    finally:
        await asyncio.gather(*(c.aclose() for c in clients.values()))
    return ExtractListLinkResponse(results=list(results))

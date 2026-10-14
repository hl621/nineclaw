"""Search service – aggregate & merge results from multiple sources."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urljoin

import httpx

from app.schemas.search import SearchRequest, SearchResponse, SearchResult, SourceHit, SourceStats
from app.services.source_loader import get_all_sources, WebSource
from app.utils.algo import lcs_ratio

logger = logging.getLogger(__name__)

# Source weight for scoring (higher = more trusted). Default 0.5 for unknown.
DEFAULT_WEIGHT = 0.5


async def do_search(req: SearchRequest) -> SearchResponse:
    """Fan out query to matching sources, merge and rank results."""
    all_sources = get_all_sources()

    include = set(req.include_sources) if req.include_sources else None
    exclude = set(req.exclude_sources)
    tag_filter = set(req.tags) if req.tags else None

    sources = [
        s for s in all_sources
        if s.enabled
        and s.request_config.get("url")
        and (tag_filter is None or tag_filter & set(s.tags))
        and (include is None or s.source_id in include)
        and s.source_id not in exclude
    ]

    # Fan out with time budget (request + parse)
    total_timeout = (req.request_timeout_ms + req.parse_timeout_ms) / 1000.0
    proxy_pool = req.proxy_pool if req.cover_default_proxy else []
    tasks = []
    for i, s in enumerate(sources):
        proxy = proxy_pool[i % len(proxy_pool)] if proxy_pool else None
        tasks.append(asyncio.create_task(_fetch_one(s, req.query, proxy, req.request_timeout_ms)))
    done, pending = await asyncio.wait(tasks, timeout=total_timeout, return_when=asyncio.ALL_COMPLETED)

    # Cancel stragglers
    for t in pending:
        t.cancel()

    per_source = [t.result() for t in done if not t.cancelled() and t.exception() is None]

    # Build weight map (apply override if provided)
    weight_map = {s.source_id: s.weight for s in sources}
    if req.cover_default_weight:
        for sid, w in req.cover_default_weight.items():
            if sid in weight_map:
                weight_map[sid] = w
    # Track timed-out sources
    source_by_task = {id(tasks[i]): sources[i] for i in range(len(sources))}
    stats: list[SourceStats] = []
    for t in pending:
        s = source_by_task[id(t)]
        stats.append(SourceStats(source_id=s.source_id, source_name=s.name, status="timeout", result_count=0, request_time_ms=req.request_timeout_ms, parse_time_ms=0, weight=s.weight, error="超时未返回"))

    if req.merge_result:
        # Merge by title similarity (LCS ratio >= 0.7)
        merged_items: list[SearchResult] = []
        for source_id, source_name, items, request_time_ms, parse_time_ms, error in per_source:
            w = weight_map.get(source_id, 0.5)
            status = "ok" if not error else "error"
            stats.append(SourceStats(source_id=source_id, source_name=source_name, status=status, result_count=len(items), request_time_ms=request_time_ms, parse_time_ms=parse_time_ms, weight=w, error=error))
            for rank, item in enumerate(items, start=1):
                hit = SourceHit(source_id=source_id, source_name=source_name, rank=rank, title=item.title, url=item.url, desc=item.desc)
                matched = _find_similar(merged_items, item.title, weight_map)
                if matched is not None:
                    matched.sources.append(hit)
                    if item.desc and (not matched.desc or len(item.desc) > len(matched.desc)):
                        matched.desc = item.desc
                    # Replace title/url if this source has higher weight
                    best_hit = max(matched.sources, key=lambda h: weight_map.get(h.source_id, 0.5))
                    if best_hit.source_id == source_id:
                        matched.title = item.title
                        matched.url = item.url
                else:
                    item.sources = [hit]
                    merged_items.append(item)
        results = _rank(merged_items, weight_map)
    else:
        # No dedup, show all results with score
        all_results: list[SearchResult] = []
        for source_id, source_name, items, request_time_ms, parse_time_ms, error in per_source:
            w = weight_map.get(source_id, 0.5)
            status = "ok" if not error else "error"
            stats.append(SourceStats(source_id=source_id, source_name=source_name, status=status, result_count=len(items), request_time_ms=request_time_ms, parse_time_ms=parse_time_ms, weight=w, error=error))
            for rank, item in enumerate(items, start=1):
                item.sources = [SourceHit(source_id=source_id, source_name=source_name, rank=rank, title=item.title, url=item.url, desc=item.desc)]
                item.score = round(w * (1.0 / rank), 4)
                all_results.append(item)
        all_results.sort(key=lambda x: x.score, reverse=True)
        results = all_results

    return SearchResponse(query=req.query, results=results[:req.limit], stats=stats)


_MERGE_THRESHOLD = 0.7


def _find_similar(items: list[SearchResult], title: str, weight_map: dict[str, float]) -> SearchResult | None:
    """Find an existing item with title LCS ratio >= threshold."""
    for item in items:
        if lcs_ratio(item.title, title) >= _MERGE_THRESHOLD:
            return item
    return None


def _rank(items: list[SearchResult], weight_map: dict[str, float]) -> list[SearchResult]:
    """Reciprocal rank fusion scoring with per-source weight."""
    return rank_results(items, weight_map)


def rank_results(items: list[SearchResult], weight_map: dict[str, float]) -> list[SearchResult]:
    """Reciprocal rank fusion scoring with per-source weight."""
    for item in items:
        score = 0.0
        for hit in item.sources:
            w = weight_map.get(hit.source_id, 0.5)
            score += w * (1.0 / hit.rank)
        item.score = round(score, 4)
    items.sort(key=lambda x: x.score, reverse=True)
    return items


async def _fetch_one(source: WebSource, query: str, proxy_override: str | None = None, request_timeout_ms: int = 10000) -> tuple[str, str, list[SearchResult], int, int, str | None]:
    """Returns (source_id, source_name, results, request_time_ms, parse_time_ms, error)."""
    cfg = source.request_config

    def sub(s: str) -> str:
        return s.replace("{query}", query)

    params = {p["key"]: sub(p["value"]) for p in cfg.get("params", []) if p.get("key")}
    headers = {h["key"]: sub(h["value"]) for h in cfg.get("headers", []) if h.get("key")}
    url = sub(cfg["url"])
    body_str = sub(cfg.get("body", ""))
    if cfg.get("method") == "POST" and body_str and "Content-Type" not in headers:
        headers["Content-Type"] = cfg.get("body_type", "application/json")

    # Proxy resolution: override > source proxy_pool > source single proxy
    proxies = None
    if proxy_override:
        proxies = {"http://": proxy_override, "https://": proxy_override}
    elif cfg.get("proxy_pool"):
        import random
        p = random.choice(cfg["proxy_pool"])
        proxies = {"http://": p, "https://": p}
    elif cfg.get("use_proxy") and cfg.get("proxy_url"):
        proxies = {"http://": cfg["proxy_url"], "https://": cfg["proxy_url"]}

    # Request phase
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxies=proxies, follow_redirects=True, timeout=request_timeout_ms / 1000.0) as client:
            resp = await client.request(
                method=cfg.get("method", "GET"),
                url=url,
                params=params or None,
                headers=headers or None,
                content=body_str.encode() if body_str else None,
            )
    except Exception as exc:
        req_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning("Source %s fetch failed: %s", source.source_id, exc)
        return (source.source_id, source.name, [], req_ms, 0, f"请求失败：{exc}")
    req_ms = int((time.perf_counter() - t0) * 1000)

    # Parse phase
    t1 = time.perf_counter()
    try:
        extract_fn = source.extract_fn
        raw = extract_fn(resp.text)
    except Exception as exc:
        parse_ms = int((time.perf_counter() - t1) * 1000)
        logger.warning("Source %s extract failed: %s", source.source_id, exc)
        return (source.source_id, source.name, [], req_ms, parse_ms, f"提取失败：{exc}")

    if not isinstance(raw, list):
        parse_ms = int((time.perf_counter() - t1) * 1000)
        return (source.source_id, source.name, [], req_ms, parse_ms, "extract() 未返回 list")

    # Build results with URL resolution
    base = source.url_base or url
    results: list[SearchResult] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_url = str(item.get("url", ""))
        if not item_url:
            continue
        if not item_url.startswith("http"):
            try:
                item_url = urljoin(base, item_url)
            except Exception:
                pass
        results.append(SearchResult(
            url=item_url,
            title=str(item.get("title", "")),
            desc=str(item["desc"]) if item.get("desc") else None,
        ))

    return (source.source_id, source.name, results, req_ms, int((time.perf_counter() - t1) * 1000), None)

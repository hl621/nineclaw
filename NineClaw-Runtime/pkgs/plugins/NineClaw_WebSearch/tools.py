"""Tool handlers — what runs when the LLM calls nineclaw_search / nineclaw_extract."""

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://nineclaw-websearch:8000"
SEARCH_ENDPOINT = "/v1/search"
EXTRACT_ENDPOINT = "/v1/extract_detail"
EXTRACT_LISTLINK_ENDPOINT = "/v1/extract_listlink"
MAX_EXTRACT_CHARS_PER_PAGE = 8000
MAX_LIST_LINKS_PER_PAGE = 30


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("NINECLAW_WEBSEARCH_ENV_FILE", "").strip()
    if override:
        paths.append(Path(os.path.expanduser(override)))
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        paths.append(Path(os.path.expanduser(hermes_home)) / ".env")
    config_path = os.environ.get("HERMES_CONFIG_PATH", "").strip()
    if config_path:
        paths.append(Path(os.path.expanduser(config_path)).parent / ".env")
    paths.append(Path(os.path.expanduser("~/.hermes/.env")))
    paths.append(Path("/opt/data/.env"))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key:
                loaded[key] = _strip_env_value(value)
    except OSError:
        return {}
    return loaded


def _load_runtime_env() -> dict[str, str]:
    loaded: dict[str, str] = {}
    for path in reversed(_env_paths()):
        loaded.update(_load_env_file(path))
    return loaded


def _load_runtime_env_file() -> None:
    for key, value in _load_runtime_env().items():
        os.environ.setdefault(key, value)


_load_runtime_env_file()


def _setting(name: str, default: str = "") -> str:
    file_value = _load_runtime_env().get(name)
    if file_value is not None and file_value.strip():
        return file_value.strip()
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value.strip()
    return default.strip()


def _resolve_base_url() -> str:
    """Resolve the NineClaw API base URL from env or default."""
    env_url = (
        _setting("NINECLAW_WEBSEARCH_BASE_URL")
        or _setting("NINECLAW_BASE_URL")
    )
    return (env_url or DEFAULT_BASE_URL).rstrip("/")


def _build_api_url(endpoint: str) -> str:
    """Build a request URL for native /v1 or manager /ws-api deployments."""
    base_url = _resolve_base_url()
    if base_url.endswith("/ws-api") and endpoint.startswith("/v1/"):
        endpoint = endpoint.removeprefix("/v1")
    return f"{base_url}{endpoint}"


def _build_headers(instance_token: str = "", source_references: list[str] | None = None) -> dict[str, str]:
    """构造 WebSearch 请求头；实例令牌为空时执行匿名运行时请求。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if source_references:
        headers["X-NineClaw-Runtime-Sources"] = ",".join(source_references)
    return headers


def _yaml_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return json.dumps(text, ensure_ascii=False)


def _yaml_block(text: Any, indent: int = 4, max_chars: int | None = None) -> list[str]:
    content = "" if text is None else str(text).strip()
    if max_chars is not None and len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n...[truncated]"
    pad = " " * indent
    if not content:
        return [f"{pad}''"]
    return [f"{pad}{line}" if line else pad for line in content.splitlines()]


def _yaml_error(message: str) -> str:
    return "\n".join([
        "status: error",
        f"error: {_yaml_escape(message)}",
    ])


def _source_label(sources: Any) -> str:
    if not isinstance(sources, list) or not sources:
        return ""
    labels: list[str] = []
    for source in sources[:3]:
        if isinstance(source, dict):
            label = source.get("name") or source.get("source") or source.get("id")
        else:
            label = source
        if label:
            labels.append(str(label))
    return ", ".join(labels)


def _format_search_yaml(result: dict) -> str:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    items = data.get("web", []) if isinstance(data, dict) else []
    query = data.get("query", "") if isinstance(data, dict) else ""
    lines = [
        "status: ok",
        f"query: {_yaml_escape(query)}",
        f"result_count: {len(items)}",
        "results:",
    ]
    if not items:
        lines.extend([
            "  []",
            "notes:",
            "  - No web snippets were returned. Broaden, narrow, or change keywords based on the public information you need.",
            "  - Use QYRAG instead if the answer should come from uploaded/internal documents.",
        ])
        return "\n".join(lines)

    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"  - rank: {item.get('position') or len(lines)}")
        lines.append(f"    title: {_yaml_escape(item.get('title', ''))}")
        lines.append(f"    url: {_yaml_escape(item.get('url', ''))}")
        source = _source_label(item.get("sources"))
        if source:
            lines.append(f"    source: {_yaml_escape(source)}")
        desc = item.get("description", "")
        lines.append("    snippet: |")
        lines.extend(_yaml_block(desc, indent=6, max_chars=900))
    lines.extend([
        "notes:",
        "  - WebSearch snippets are broad and current but scattered; extract promising URLs before relying on details.",
        "  - Refine keywords or sources when exploring public information.",
        "  - If the user needs authoritative uploaded-file evidence, use QYRAG or combine both tools.",
    ])
    return "\n".join(lines)


def _format_extract_yaml(result: dict) -> str:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    items = data.get("extracted", []) if isinstance(data, dict) else []
    lines = [
        "status: ok",
        f"page_count: {len(items)}",
        "pages:",
    ]
    if not items:
        lines.append("  []")
        return "\n".join(lines)

    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(f"  - title: {_yaml_escape(item.get('title', ''))}")
        lines.append(f"    url: {_yaml_escape(item.get('url', ''))}")
        if item.get("publish_date"):
            lines.append(f"    publish_date: {_yaml_escape(item.get('publish_date'))}")
        if item.get("error"):
            lines.append(f"    error: {_yaml_escape(item.get('error'))}")
            continue
        lines.append("    content: |")
        lines.extend(_yaml_block(item.get("content", ""), indent=6, max_chars=MAX_EXTRACT_CHARS_PER_PAGE))
    lines.extend([
        "notes:",
        "  - Treat extracted web pages as public-source evidence; check date, source quality, and conflicts with QYRAG document evidence.",
    ])
    return "\n".join(lines)


def _flatten_link_blocks(blocks: Any) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []

    def add_link(value: Any) -> None:
        if isinstance(value, dict):
            url = str(value.get("url") or value.get("href") or value.get("link") or "").strip()
            title = str(value.get("title") or value.get("text") or value.get("name") or "").strip()
            if url:
                links.append({"title": title, "url": url})
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            links.append({"title": "", "url": value})

    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict):
                nested = block.get("links") or block.get("items") or block.get("urls")
                if isinstance(nested, list):
                    for item in nested:
                        add_link(item)
                else:
                    add_link(block)
            else:
                add_link(block)
    elif isinstance(blocks, dict):
        for key in ("links", "items", "urls"):
            nested = blocks.get(key)
            if isinstance(nested, list):
                for item in nested:
                    add_link(item)
    return links


def _format_listlink_yaml(result: dict) -> str:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    pages = data.get("link_pages", []) if isinstance(data, dict) else []
    lines = [
        "status: ok",
        f"page_count: {len(pages)}",
        "pages:",
    ]
    if not pages:
        lines.append("  []")
        return "\n".join(lines)

    for page in pages:
        if not isinstance(page, dict):
            continue
        links = _flatten_link_blocks(page.get("link_blocks"))[:MAX_LIST_LINKS_PER_PAGE]
        lines.append(f"  - url: {_yaml_escape(page.get('url', ''))}")
        if page.get("error"):
            lines.append(f"    error: {_yaml_escape(page.get('error'))}")
        lines.append(f"    link_count_shown: {len(links)}")
        lines.append("    links:")
        if not links:
            lines.append("      []")
            continue
        for link in links:
            lines.append(f"      - title: {_yaml_escape(link.get('title', ''))}")
            lines.append(f"        url: {_yaml_escape(link.get('url', ''))}")
    lines.extend([
        "notes:",
        "  - Use nineclaw_extract on the most relevant exact URLs; do not rely on link titles alone.",
    ])
    return "\n".join(lines)


def _split_env_list(value: str) -> list[str]:
    """Parse comma/newline separated env values."""
    if not value:
        return []
    normalized = value.replace("\n", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _env_list(name: str) -> list[str]:
    return _split_env_list(_setting(name))


def _normalize_input_urls(value: Any) -> tuple[list[str], str | None]:
    if not value or not isinstance(value, list):
        return [], "urls cannot be empty"

    urls = [u.strip() for u in value if isinstance(u, str) and u.strip()]
    if not urls:
        return [], "urls cannot be empty"

    abbreviated = [u for u in urls if "..." in u or "\u2026" in u]
    if abbreviated:
        return [], (
            "urls must be complete, exact http(s) URLs. Do not use shortened or "
            "display-truncated URLs containing '...' or an ellipsis; provide the "
            f"full URL instead. Invalid URL: {abbreviated[0]}"
        )

    invalid = [
        u
        for u in urls
        if (parsed := urlparse(u)).scheme not in {"http", "https"} or not parsed.netloc
    ]
    if invalid:
        return [], f"urls must be complete http(s) URLs. Invalid URL: {invalid[0]}"

    return urls, None


def _configured_include_sources() -> list[str]:
    """读取 Runtime 固定的 WebSearch 信源白名单。"""
    return _env_list("NINECLAW_WEBSEARCH_INCLUDE_SOURCES")


def _configured_exclude_sources() -> list[str]:
    return (
        _env_list("NINECLAW_WEBSEARCH_EXCLUDE_SOURCES")
        or _env_list("NINECLAW_EXCLUDE_SOURCES")
    )


def _configured_tags() -> list[str]:
    return _env_list("NINECLAW_WEBSEARCH_TAGS") or _env_list("NINECLAW_TAGS")


# ─────────────────────────────────────────────────────────────────────────────
# Tool handler: nineclaw_search
# ─────────────────────────────────────────────────────────────────────────────


def _search_error(message: str, structured: bool) -> dict | str:
    """按调用方需求返回结构化错误或 YAML 工具错误。"""
    if structured:
        return {"success": False, "error": message}
    return _yaml_error(message)


def handle_nineclaw_search(params: dict, **kwargs) -> dict | str:
    """Search using NineClaw WebSearch API.

    POST /v1/search

    Parameters:
      - query (required): Search query string
      - limit: Number of results (default 20)
      - include_sources: List of source IDs to search
      - exclude_sources: List of source IDs to exclude
      - tags: Filter by tags
      - merge_result: Whether to merge multi-source results (default true)
      - request_timeout_ms: Per-source request timeout (default 10000)
      - parse_timeout_ms: Parse timeout (default 5000)
      - proxy_pool: Global proxy pool, rotated per source
      - cover_default_proxy: Whether proxy_pool overrides source-level proxy config
      - cover_default_weight: Source weight overrides, keyed by source ID
    """
    structured = bool(kwargs.pop("structured", False))
    query = (params.get("query") or "").strip()
    if not query:
        return _search_error("query cannot be empty", structured)

    raw_limit = params.get("limit", 20)
    try:
        limit = max(1, min(int(raw_limit), 100))
    except (TypeError, ValueError):
        limit = 20

    # Build request body
    body: dict = {"query": query, "limit": limit}

    include_sources = _configured_include_sources()
    if not include_sources:
        return _search_error(
            "未配置 NINECLAW_WEBSEARCH_INCLUDE_SOURCES，禁止执行搜索",
            structured,
        )
    body["include_sources"] = include_sources

    tags = _configured_tags()
    if tags:
        body["tags"] = tags

    merge_result = params.get("merge_result")
    if merge_result is not None:
        body["merge_result"] = bool(merge_result)

    request_timeout_ms = params.get("request_timeout_ms", 10000)
    try:
        body["request_timeout_ms"] = max(1000, min(int(request_timeout_ms), 60000))
    except (TypeError, ValueError):
        body["request_timeout_ms"] = 10000

    parse_timeout_ms = params.get("parse_timeout_ms", 5000)
    try:
        body["parse_timeout_ms"] = max(1000, min(int(parse_timeout_ms), 60000))
    except (TypeError, ValueError):
        body["parse_timeout_ms"] = 5000

    url = _build_api_url(SEARCH_ENDPOINT)
    headers = _build_headers(source_references=include_sources)
    # Server-side search waits for request_timeout_ms + parse_timeout_ms.
    # Keep the client budget slightly larger so the server can return its
    # own timeout/error stats instead of the client disconnecting first.
    timeout = (body["request_timeout_ms"] + body["parse_timeout_ms"]) / 1000.0 + 5.0

    logger.info(
        "NineClaw search: '%s' (limit=%d, base=%s)",
        query, limit, url,
    )

    try:
        resp = httpx.post(
            url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body_text = exc.response.text[:500]
        logger.error("NineClaw HTTP %s: %s", status, body_text)
        if status == 422:
            return _search_error(f"Validation error (HTTP 422): {body_text[:300]}", structured)
        return _search_error(f"NineClaw API error (HTTP {status}): {body_text[:200]}", structured)
    except httpx.TimeoutException:
        logger.error("NineClaw search timed out after %.1fs", timeout)
        return _search_error(
            f"NineClaw search timed out ({timeout:.0f}s). Try a simpler query or reduce limit.",
            structured,
        )
    except httpx.RequestError as exc:
        logger.error("NineClaw request error: %s", exc)
        return _search_error(f"NineClaw request failed: {exc}", structured)

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("NineClaw returned invalid JSON: %s", exc)
        return _search_error(f"NineClaw returned invalid JSON: {exc}", structured)

    # Normalize to Hermes standard format
    result = _normalize_search_response(data)
    web = result.get("data", {}).get("web", [])
    logger.info("NineClaw search returned %d results", len(web))
    return result if structured else _format_search_yaml(result)


def _normalize_search_response(data: dict) -> dict:
    """Normalize NineClaw SearchResponse to Hermes standard format."""
    raw_results = data.get("results", []) or []
    query = data.get("query", "")
    stats = data.get("stats", [])

    web_results = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        desc = entry.get("desc") or ""
        score = entry.get("score") or 0.0
        sources = entry.get("sources", []) or []

        if not url and not title:
            continue

        web_results.append({
            "url": url,
            "title": title,
            "description": desc,
            "score": score,
            "sources": sources,
            "position": len(web_results) + 1,
        })

    return {
        "success": True,
        "data": {
            "web": web_results,
            "query": query,
            "stats": stats,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool handler: nineclaw_extract
# ─────────────────────────────────────────────────────────────────────────────


def _extract_error(message: str, structured: bool) -> dict | str:
    """按调用方需求返回结构化错误或 YAML 工具错误。"""
    if structured:
        return {"success": False, "error": message}
    return _yaml_error(message)


def handle_nineclaw_extract(params: dict, **kwargs) -> dict | str:
    """Extract full content from URLs using NineClaw WebSearch API.

    POST /v1/extract_detail

    Parameters:
      - urls (required): List of URLs to extract
      - proxies: Optional proxy list
    """
    structured = bool(kwargs.pop("structured", False))
    return _extract_error(
        "当前插件仅允许使用已配置信源搜索，不支持任意 URL 网页提取",
        structured,
    )

def handle_nineclaw_extract_listlink(params: dict, **kwargs) -> str:
    """Extract related/list links from URLs using NineClaw WebSearch API.

    POST /v1/extract_listlink

    Use this when a page is an index/listing/search-result/category page and
    the next step is horizontal expansion: discovering article/detail URLs to
    search or extract later. It does not fetch full article body text.
    """
    return _yaml_error(
        "当前插件仅允许使用已配置信源搜索，不支持任意 URL 链接提取"
    )

#!/usr/bin/env python3
"""hermes-nineclaw-websearch - CLI for NineClaw WebSearch.

Usage:
    hermes-nineclaw-websearch search "query string"
    hermes-nineclaw-websearch search -q "query" --include-source bing --tag news
    hermes-nineclaw-websearch extract https://example.com/article
    hermes-nineclaw-websearch listlink https://example.com/topic
    echo "query" | hermes-nineclaw-websearch search

Env:
    NINECLAW_WEBSEARCH_BASE_URL - Optional. Default: http://nineclaw-websearch:8000
    NINECLAW_WEBSEARCH_INCLUDE_SOURCES - Optional comma-separated source allowlist
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _load_env_file() -> None:
    """Load environment variables from Hermes .env file if present."""
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def _ensure_import_path() -> None:
    """Make the plugin importable from Hermes and source checkout layouts."""
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(plugin_dir)
    hermes_plugins = os.path.expanduser("~/.hermes/plugins")
    for path in (plugin_dir, parent_dir, hermes_plugins):
        if path and path not in sys.path:
            sys.path.insert(0, path)


_load_env_file()
_ensure_import_path()

try:
    from NineClaw_WebSearch.tools import (
        handle_nineclaw_extract,
        handle_nineclaw_extract_listlink,
        handle_nineclaw_search,
    )
except ImportError:
    # Installed plugin directory may be named differently by the user.
    from tools import (  # type: ignore
        handle_nineclaw_extract,
        handle_nineclaw_extract_listlink,
        handle_nineclaw_search,
    )


def _csv_or_repeated(values: list[str] | None) -> list[str]:
    """Parse repeated flags that may also contain comma-separated values."""
    parsed: list[str] = []
    for value in values or []:
        parsed.extend(part.strip() for part in value.split(",") if part.strip())
    return parsed


def _load_json_result(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON from handler: {exc}", "raw": raw}
    if isinstance(payload, dict):
        return payload
    return {"success": False, "error": "Handler returned non-object JSON", "raw": payload}


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_search(payload: dict[str, Any]) -> int:
    if not payload.get("success"):
        print(f"Error: {payload.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    data = payload.get("data", {}) or {}
    web_results = data.get("web", []) or []
    query = data.get("query")
    stats = data.get("stats")

    if query:
        print(f"Query: {query}")
    if stats:
        print(f"Stats: {json.dumps(stats, ensure_ascii=False)}")

    if not web_results:
        print("(No results returned)")
        return 0

    for entry in web_results:
        title = entry.get("title", "")
        url = entry.get("url", "")
        description = entry.get("description", "")
        sources = entry.get("sources")
        score = entry.get("score")
        position = entry.get("position")

        heading = f"\n[{position}] {title}" if position else f"\n# {title}"
        print(heading)
        if url:
            print(f"URL: {url}")
        if score is not None:
            print(f"Score: {score}")
        if sources:
            print(f"Sources: {', '.join(str(s) for s in sources)}")
        if description:
            print(description[:800])
        print("-" * 60)
    return 0


def _print_extract(payload: dict[str, Any], max_chars: int) -> int:
    if not payload.get("success"):
        print(f"Error: {payload.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    extracted = (payload.get("data", {}) or {}).get("extracted", []) or []
    if not extracted:
        print("(No content returned)")
        return 0

    for entry in extracted:
        url = entry.get("url", "")
        title = entry.get("title", "")
        content = entry.get("content") or ""
        error = entry.get("error")
        publish_date = entry.get("publish_date")

        print(f"\n# {title or url}")
        if url:
            print(f"URL: {url}")
        if publish_date:
            print(f"Publish date: {publish_date}")
        if error:
            print(f"Error: {error}", file=sys.stderr)
        if content:
            display = content if max_chars <= 0 else content[:max_chars]
            print(display)
            if max_chars > 0 and len(content) > max_chars:
                print(f"\n[truncated: showing {max_chars} of {len(content)} chars]")
        print("-" * 60)
    return 0


def _print_listlink(payload: dict[str, Any]) -> int:
    if not payload.get("success"):
        print(f"Error: {payload.get('error', 'Unknown error')}", file=sys.stderr)
        return 1

    link_pages = (payload.get("data", {}) or {}).get("link_pages", []) or []
    if not link_pages:
        print("(No links returned)")
        return 0

    for page in link_pages:
        url = page.get("url", "")
        error = page.get("error")
        print(f"\n# {url}")
        if error:
            print(f"Error: {error}", file=sys.stderr)
        for block in page.get("link_blocks") or []:
            xpath = block.get("link_xpath", "")
            if xpath:
                print(f"Block: {xpath}")
            for item in block.get("link_items") or []:
                title = item.get("title") or ""
                link = item.get("url") or ""
                if title and link:
                    print(f"- {title}: {link}")
                elif link:
                    print(f"- {link}")
        print("-" * 60)
    return 0


def _add_search_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "search",
        help="Search the web via NineClaw",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hermes-nineclaw-websearch search "latest AI news"
  hermes-nineclaw-websearch search -q "台湾海峡 美舰 穿航" --include-source bing --include-source baidu
  hermes-nineclaw-websearch search -q "OpenAI docs" --exclude-source twitter --tag docs
  echo "query" | hermes-nineclaw-websearch search --limit 5
        """,
    )
    parser.add_argument("query_positional", nargs="?", help="Search query")
    parser.add_argument("-q", "--query", dest="query_flag", help="Search query")
    parser.add_argument("-l", "--limit", type=int, default=20, help="Number of results (1-100, default: 20)")
    parser.add_argument("--include-source", action="append", help="Only search these source IDs. Repeat or comma-separate.")
    parser.add_argument("--exclude-source", action="append", help="Exclude these source IDs. Repeat or comma-separate.")
    parser.add_argument("--tag", action="append", help="Filter by tags. Repeat or comma-separate.")
    parser.add_argument("--proxy", action="append", dest="search_proxy", help="Search proxy pool entry. Repeat or comma-separate.")
    parser.add_argument("--cover-default-proxy", action="store_true", help="Make --proxy override source-level proxy config.")
    parser.add_argument(
        "--source-weight",
        action="append",
        help="Override ranking weight as source_id=weight. Repeatable.",
    )
    parser.add_argument("--no-merge", action="store_true", help="Disable multi-source result merging.")
    parser.add_argument("--request-timeout-ms", type=int, default=10000, help="Per-source timeout in ms.")
    parser.add_argument("--parse-timeout-ms", type=int, default=5000, help="Parse timeout in ms.")
    parser.add_argument("-j", "--json", action="store_true", help="Output raw JSON.")


def _add_extract_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "extract",
        help="Extract full page content via NineClaw",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hermes-nineclaw-websearch extract https://example.com/article
  hermes-nineclaw-websearch extract --url https://a.test --url https://b.test --max-chars 2000
  cat urls.txt | hermes-nineclaw-websearch extract --json
        """,
    )
    parser.add_argument("urls_positional", nargs="*", help="URLs to extract")
    parser.add_argument("--url", action="append", dest="urls_flag", help="URL to extract. Repeatable.")
    parser.add_argument("--proxy", action="append", help="Proxy URL. Repeat or comma-separate.")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max content chars per page for text output. 0 means unlimited.")
    parser.add_argument("-j", "--json", action="store_true", help="Output raw JSON.")


def _add_listlink_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "listlink",
        help="Discover related links from list/index pages via NineClaw",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hermes-nineclaw-websearch listlink https://example.com/topic
  hermes-nineclaw-websearch listlink --url https://a.test --url https://b.test --json
  cat urls.txt | hermes-nineclaw-websearch listlink
        """,
    )
    parser.add_argument("urls_positional", nargs="*", help="List/index URLs to scan")
    parser.add_argument("--url", action="append", dest="urls_flag", help="URL to scan. Repeatable.")
    parser.add_argument("--proxy", action="append", help="Proxy URL. Repeat or comma-separate.")
    parser.add_argument("-j", "--json", action="store_true", help="Output raw JSON.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search and extract pages using NineClaw WebSearch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  NINECLAW_WEBSEARCH_BASE_URL  Optional. Default: http://nineclaw-websearch:8000
  NINECLAW_WEBSEARCH_INCLUDE_SOURCES  Optional comma-separated source allowlist

Commands:
  search   Search with optional source/tag filters
  extract  Extract full content from one or more URLs
  listlink Discover related links from list/index pages
        """,
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_search_parser(subparsers)
    _add_extract_parser(subparsers)
    _add_listlink_parser(subparsers)
    return parser


def _run_search(args: argparse.Namespace) -> int:
    query = args.query_positional or args.query_flag
    if not query and not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    if not query:
        print("Error: query is required", file=sys.stderr)
        return 1

    params: dict[str, Any] = {
        "query": query,
        "limit": args.limit,
        "request_timeout_ms": args.request_timeout_ms,
        "parse_timeout_ms": args.parse_timeout_ms,
    }
    include_sources = _csv_or_repeated(args.include_source)
    exclude_sources = _csv_or_repeated(args.exclude_source)
    tags = _csv_or_repeated(args.tag)
    proxy_pool = _csv_or_repeated(args.search_proxy)
    if include_sources:
        params["include_sources"] = include_sources
    if exclude_sources:
        params["exclude_sources"] = exclude_sources
    if tags:
        params["tags"] = tags
    if proxy_pool:
        params["proxy_pool"] = proxy_pool
    if args.cover_default_proxy:
        params["cover_default_proxy"] = True
    weights: dict[str, float] = {}
    for item in args.source_weight or []:
        if "=" not in item:
            print(f"Error: invalid --source-weight '{item}', expected source_id=weight", file=sys.stderr)
            return 1
        source_id, raw_weight = item.split("=", 1)
        try:
            weights[source_id.strip()] = float(raw_weight)
        except ValueError:
            print(f"Error: invalid weight in --source-weight '{item}'", file=sys.stderr)
            return 1
    if weights:
        params["cover_default_weight"] = weights
    if args.no_merge:
        params["merge_result"] = False

    payload = _load_json_result(handle_nineclaw_search(params))
    if args.json:
        _print_json(payload)
        return 0 if payload.get("success") else 1
    return _print_search(payload)


def _run_extract(args: argparse.Namespace) -> int:
    urls = list(args.urls_positional or []) + _csv_or_repeated(args.urls_flag)
    if not urls and not sys.stdin.isatty():
        urls = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if not urls:
        print("Error: at least one URL is required", file=sys.stderr)
        return 1

    params: dict[str, Any] = {"urls": urls}
    proxies = _csv_or_repeated(args.proxy)
    if proxies:
        params["proxies"] = proxies

    payload = _load_json_result(handle_nineclaw_extract(params))
    if args.json:
        _print_json(payload)
        return 0 if payload.get("success") else 1
    return _print_extract(payload, max_chars=args.max_chars)


def _run_listlink(args: argparse.Namespace) -> int:
    urls = list(args.urls_positional or []) + _csv_or_repeated(args.urls_flag)
    if not urls and not sys.stdin.isatty():
        urls = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if not urls:
        print("Error: at least one URL is required", file=sys.stderr)
        return 1

    params: dict[str, Any] = {"urls": urls}
    proxies = _csv_or_repeated(args.proxy)
    if proxies:
        params["proxies"] = proxies

    payload = _load_json_result(handle_nineclaw_extract_listlink(params))
    if args.json:
        _print_json(payload)
        return 0 if payload.get("success") else 1
    return _print_listlink(payload)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "search":
        return _run_search(args)
    if args.command == "extract":
        return _run_extract(args)
    if args.command == "listlink":
        return _run_listlink(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

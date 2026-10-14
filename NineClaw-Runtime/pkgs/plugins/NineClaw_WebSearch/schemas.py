"""Tool schemas — what the LLM sees when deciding to call NineClaw tools."""

NINECLAW_SEARCH_SCHEMA = {
    "name": "nineclaw_search",
    "description": (
        "Call NineClaw WebSearch POST /v1/search to retrieve ranked snippets only from runtime-configured and authorized sources. The source range is fixed by NINECLAW_WEBSEARCH_INCLUDE_SOURCES; tool parameters cannot expand or replace it. Do not use this tool for public internet discovery. When the configured sources have no evidence or are unavailable, report that limitation. Returns concise YAML with title, URL, snippet, and source labels."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The search query. Be specific and include key context words. "
                    "Example: 'latest GPT-5 release date' or 'AI agent framework comparison'"
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (1–100, default 20).",
                "default": 20,
                "minimum": 1,
                "maximum": 100,
            },
            "include_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ignored. The runtime-fixed NINECLAW_WEBSEARCH_INCLUDE_SOURCES allowlist is always used."
                ),
            },
            "exclude_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude specific data sources from search.",
                "default": [],
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter results by tags.",
            },
            "proxy_pool": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Global proxy pool for search source requests. Rotated per source.",
                "default": [],
            },
            "cover_default_proxy": {
                "type": "boolean",
                "description": "If true, proxy_pool overrides each source's default proxy config.",
                "default": False,
            },
            "cover_default_weight": {
                "type": "object",
                "additionalProperties": {"type": "number"},
                "description": "Override source weights for ranking, keyed by source_id.",
                "default": {},
            },
            "merge_result": {
                "type": "boolean",
                "description": "Whether to merge results from multiple sources (default: true).",
                "default": True,
            },
            "request_timeout_ms": {
                "type": "integer",
                "description": "Timeout per source request in milliseconds (default: 10000).",
                "default": 10000,
                "minimum": 1000,
                "maximum": 60000,
            },
            "parse_timeout_ms": {
                "type": "integer",
                "description": "Timeout for parsing results in milliseconds (default: 5000).",
                "default": 5000,
                "minimum": 1000,
                "maximum": 60000,
            },
        },
        "required": ["query"],
    },
}

NINECLAW_EXTRACT_SCHEMA = {
    "name": "nineclaw_extract",
    "description": (
        "Disabled in this deployment. The plugin only permits configured-source search and rejects arbitrary URL extraction. Use this after nineclaw_search "
        "when snippets are not enough, for citation-grade details, long-form "
        "articles, official pages, or source verification. Do not use this for "
        "broad discovery; search first. For finding more links on an index page, "
        "use nineclaw_extract_listlink instead. URLs must be complete, exact, "
        "clickable http(s) URLs; never pass shortened or display-truncated URLs "
        "containing '...' or an ellipsis. Returns concise YAML with title, URL, publish_date when available, and extracted content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of complete, exact http(s) URLs to extract content from. "
                    "Use the full URL returned by search or copied from the source. "
                    "Do not invent, shorten, summarize, or include display-truncated "
                    "URLs containing '...' or an ellipsis; if only a shortened URL is "
                    "available, search again or ask for the full URL. "
                    "Example: ['https://example.com/article1', 'https://example.com/article2']"
                ),
            },
            "proxies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional proxy list for extraction.",
                "default": [],
            },
        },
        "required": ["urls"],
    },
}

NINECLAW_EXTRACT_LISTLINK_SCHEMA = {
    "name": "nineclaw_extract_listlink",
    "description": (
        "Disabled in this deployment. The plugin only permits configured-source search and rejects arbitrary URL link extraction. Use this for horizontal expansion from "
        "portal pages, category pages, search result pages, topic pages, archive "
        "pages, or any URL likely to contain lists of article/detail links. This "
        "does not extract full article text; after finding useful URLs, call "
        "nineclaw_extract for body content. URLs must be complete, exact, clickable "
        "http(s) URLs; never pass shortened or display-truncated URLs containing "
        "'...' or an ellipsis. Returns concise YAML listing candidate exact URLs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Complete, exact list/index URLs to scan for related links. "
                    "Do not use URLs containing '...' or an ellipsis; obtain the "
                    "full URL first."
                ),
            },
            "proxies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional proxy list for link extraction.",
                "default": [],
            },
        },
        "required": ["urls"],
    },
}

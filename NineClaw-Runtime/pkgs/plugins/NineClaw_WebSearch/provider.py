"""NineClaw WebSearchProvider — registers as a configured-source backend.

Follows the same pattern as built-in providers (searxng, brave-free, ddgs, etc.).
Only supports searches through runtime-configured sources.
"""

from __future__ import annotations

import logging
from typing import Any, Dict


from agent.web_search_provider import WebSearchProvider

from .tools import handle_nineclaw_search

logger = logging.getLogger(__name__)


class NineClawWebProvider(WebSearchProvider):
    """NineClaw as a web search backend."""

    @property
    def name(self) -> str:
        return "nineclaw"

    @property
    def display_name(self) -> str:
        return "NineClaw WebSearch"

    def is_available(self) -> bool:
        """NineClaw is always available (internal service)."""
        return True

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        """禁止任意 URL 提取，避免绕过运行时信源白名单。"""
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Execute search via NineClaw.

        Return shape:
            {"success": True, "data": {"web": [{"title", "url", "description", "position"}]}}
        """
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            payload = handle_nineclaw_search(
                {
                    "query": query,
                    "limit": limit,
                },
                structured=True,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("NineClaw search error: %s", exc)
            return {"success": False, "error": f"NineClaw search failed: {exc}"}

        if not payload.get("success"):
            return payload

        # Keep only the stable Hermes web_search fields for provider dispatch.
        web_results = []
        for i, item in enumerate(payload.get("data", {}).get("web", []) or [], 1):
            if not isinstance(item, dict):
                continue
            source_names: list[str] = []
            for source in item.get("sources", []) or []:
                if not isinstance(source, dict):
                    continue
                source_name = str(
                    source.get("source_name")
                    or source.get("source_id")
                    or source.get("name")
                    or source.get("id")
                    or ""
                ).strip()
                if source_name and source_name not in source_names:
                    source_names.append(source_name)

            description = item.get("description", "") or ""
            if source_names:
                # 使用服务端返回的信源标识，区分检索入口与结果链接域名。
                source_label = "、".join(source_names)
                description = f"检索源：{source_label}\n{description}"
            web_results.append(
                {
                    "title": item.get("title", "") or "",
                    "url": item.get("url", "") or "",
                    "description": description,
                    "position": int(item.get("position") or i),
                }
            )
        return {"success": True, "data": {"web": web_results}}

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "NineClaw WebSearch",
            "badge": "configured sources only",
            "tag": (
                "Only searches sources configured by NINECLAW_WEBSEARCH_INCLUDE_SOURCES. "
                "Arbitrary URL extraction is disabled."
            ),
            "env_vars": [
                {
                    "key": "NINECLAW_WEBSEARCH_BASE_URL",
                    "prompt": "NineClaw WebSearch base URL (optional, default: http://nineclaw-websearch:8000)",
                    "url": "",
                },
                {
                    "key": "NINECLAW_WEBSEARCH_INCLUDE_SOURCES",
                    "prompt": "Required comma-separated source references. The plugin cannot search outside this list.",
                    "url": "",
                },
            ],
        }

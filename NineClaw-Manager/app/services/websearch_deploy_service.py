"""Push WebSearch plugin settings to NineClaw instances via Hermes Dashboard."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

ENV_HERMES_ENABLE_PROJECT_PLUGINS = "HERMES_ENABLE_PROJECT_PLUGINS"
ENV_WEBSEARCH_BASE_URL = "NINECLAW_WEBSEARCH_BASE_URL"
ENV_WEBSEARCH_INCLUDE_SOURCES = "NINECLAW_WEBSEARCH_INCLUDE_SOURCES"
WEBSEARCH_PLUGIN_ID = "NineClaw-WebSearch"
WEBSEARCH_CONFIG_BLOCK = {
    "backend": "nineclaw",
    "search_backend": "nineclaw",
    "extract_backend": "nineclaw",
    "use_gateway": False,
}
WEBSEARCH_REQUIRED_TOOLSETS = ("web", "hermes-cli")


def websearch_runtime_base_url() -> str:
    return f"{settings.resolved_traefik_url}/ws-api"


def build_websearch_deploy_env(source_ids: list[str]) -> dict[str, str]:
    return {
        ENV_HERMES_ENABLE_PROJECT_PLUGINS: "1",
        ENV_WEBSEARCH_BASE_URL: websearch_runtime_base_url(),
        ENV_WEBSEARCH_INCLUDE_SOURCES: ",".join(
            sid.strip() for sid in source_ids if isinstance(sid, str) and sid.strip()
        ),
    }


def merge_websearch_config(current: Any) -> dict[str, Any]:
    config = dict(current) if isinstance(current, dict) else {}
    web_config = config.get("web")
    config["web"] = {
        **(web_config if isinstance(web_config, dict) else {}),
        **WEBSEARCH_CONFIG_BLOCK,
    }
    toolsets = config.get("toolsets")
    merged_toolsets = (
        [item for item in toolsets if isinstance(item, str)]
        if isinstance(toolsets, list)
        else []
    )
    for toolset in WEBSEARCH_REQUIRED_TOOLSETS:
        if toolset not in merged_toolsets:
            merged_toolsets.append(toolset)
    config["toolsets"] = merged_toolsets
    return config

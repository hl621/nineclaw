"""NineClaw WebSearch plugin for Hermes Agent.

Registers:
  - WebSearchProvider "nineclaw" -> integrates with configured-source search dispatch
  - nineclaw_search -> direct /v1/search with a runtime-fixed source allowlist

Env vars (set in ~/.hermes/.env):
  NINECLAW_WEBSEARCH_BASE_URL       — Optional service URL written by NineClaw-WebUI
  NINECLAW_WEBSEARCH_INCLUDE_SOURCES — Required comma-separated source allowlist
"""

from .provider import NineClawWebProvider


def register(ctx) -> None:
    """Register NineClaw as a fixed-source search backend."""
    ctx.register_web_search_provider(NineClawWebProvider())

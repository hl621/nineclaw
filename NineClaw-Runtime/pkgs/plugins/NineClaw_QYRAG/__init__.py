"""NineClaw-QYRAG plugin for Hermes Agent.

Provides tools to retrieve chunks from QYRAG knowledge bases
via the /api/v1/retrieval API. Supports semantic search, keyword
matching, metadata filtering, cross-language retrieval, knowledge
graph enhanced search, and TOC enhanced search.

Environment Variables:
    QYRAG_BASE_URL: QYRAG server URL (default: http://172.18.33.24:8513)
    QYRAG_API_KEY:  API key for authentication

Installation:
    mkdir -p ~/.hermes/plugins/QYRAG_retrieval
    # Drop plugin.yaml, __init__.py, schemas.py, tools.py in that directory
    # Then restart or /reset. Tools appear automatically.
"""

from .schemas import (
    QYRAG_ANSWER,
    QYRAG_CHECK_SUFFICIENT_CONTEXT,
    QYRAG_EXPAND_CONTEXT,
    QYRAG_GREP_DOCUMENT,
    # QYRAG_HEALTH_CHECK,
    QYRAG_RETRIEVE,
    QYRAG_SAVE_DOCUMENT,
)
from .tools import (
    QYRAG_answer,
    QYRAG_check_sufficient_context,
    QYRAG_expand_context,
    QYRAG_grep_document,
    # QYRAG_health_check,
    QYRAG_retrieve,
    QYRAG_save_document,
)


def register(ctx) -> None:
    """Register NineClaw-QYRAG tools with Hermes via PluginContext."""
    # 1. Answer directly from the selected knowledge base.
    # 直接从选定知识库中回答问题。
    # ctx.register_tool("QYRAG_answer", "QYRAG_retrieval", QYRAG_ANSWER, QYRAG_answer)

    ctx.register_tool(
        "QYRAG_retrieve", "web", QYRAG_RETRIEVE, QYRAG_retrieve
    )
    ctx.register_tool(
        "QYRAG_check_sufficient_context",
        "web",
        QYRAG_CHECK_SUFFICIENT_CONTEXT,
        QYRAG_check_sufficient_context,
    )
    ctx.register_tool(
        "QYRAG_grep_document",
        "web",
        QYRAG_GREP_DOCUMENT,
        QYRAG_grep_document,
    )

    # 2. Health check tool
    # ctx.register_tool(
    #     "QYRAG_health_check",
    #     "QYRAG_retrieval",
    #     # QYRAG_HEALTH_CHECK,
    #     # QYRAG_health_check,
    # )

    # 3. Expand context around a relevant chunk
    ctx.register_tool(
        "QYRAG_expand_context",
        "web",
        QYRAG_EXPAND_CONTEXT,
        QYRAG_expand_context,
    )

    # 4. Save document material into workspace
    ctx.register_tool(
        "QYRAG_save_document",
        "web",
        QYRAG_SAVE_DOCUMENT,
        QYRAG_save_document,
    )

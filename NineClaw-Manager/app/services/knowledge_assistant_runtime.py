"""Public-facing service aliases for knowledge assistant runtime."""

from __future__ import annotations

from app.services.knowledge_agno_qa_runtime import (
    LEGACY_SSE_HEADERS,
    cancel_studio_run,
    create_studio_session,
    knowledge_agno_qa_stream,
    process_agno_studio_qa_stream,
)
from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_llm_service import QaLlmConfig


async def knowledge_assistant_qa_service(
    *,
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int = 5,
    rerank_id: str | None = None,
    tenant_rerank_id: str | int | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
    llm: QaLlmConfig | None = None,
):
    """Global / multi-KB QA via the same AgenticRAG agent as Studio.

    Uses ``knowledge_agno_qa_stream`` so the legacy SSE shape
    (references → content → [DONE]) stays compatible with the global
    search page, while retrieval/answer logic matches single-KB Studio.
    """
    async for event in knowledge_agno_qa_stream(
        service,
        question=question,
        dataset_ids=dataset_ids,
        top_k=top_k,
        rerank_id=rerank_id,
        tenant_rerank_id=tenant_rerank_id,
        temperature=temperature,
        enable_thinking=enable_thinking,
        llm=llm,
    ):
        yield event


process_knowledge_studio_assistant_stream = process_agno_studio_qa_stream
create_knowledge_studio_assistant_session = create_studio_session

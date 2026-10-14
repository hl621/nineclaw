"""Regression tests for RAGFlow bulkhead isolation."""

from __future__ import annotations

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import knowledge as knowledge_route
from app.main import app
from app.services.ragflow_knowledge_service import RagflowKnowledgeService


class SlowRagflowKnowledgeService(RagflowKnowledgeService):
    def __init__(self) -> None:
        pass

    def list_knowledge(self) -> list[dict]:
        time.sleep(0.3)
        return []


@pytest.mark.asyncio
async def test_slow_ragflow_list_does_not_block_event_loop() -> None:
    app.dependency_overrides[knowledge_route.get_knowledge_service_dep] = (
        lambda: SlowRagflowKnowledgeService()
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            slow_request = asyncio.create_task(ac.get("/v1/knowledge"))
            await asyncio.sleep(0.05)

            started = time.perf_counter()
            health = await ac.get("/health")
            elapsed = time.perf_counter() - started

            assert health.status_code == 200
            assert elapsed < 0.15
            assert (await slow_request).status_code == 200
    finally:
        app.dependency_overrides.pop(knowledge_route.get_knowledge_service_dep, None)

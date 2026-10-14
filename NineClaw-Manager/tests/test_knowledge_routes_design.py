"""Route-shape tests for public knowledge APIs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_public_knowledge_routes_do_not_expose_agent_framework(client) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200

    spec = resp.json()
    paths = set(spec["paths"])
    assert "/v1/knowledge/qa" in paths
    assert "/v1/knowledge/{kb_id}/studio/chat/session" in paths
    assert "/v1/knowledge/{kb_id}/studio/chat/qa" in paths
    assert "/v1/knowledge/{kb_id}/qa" not in paths
    assert not any("agno" in path.lower() for path in paths)
    assert "/v1/knowledge/qa/assistant" not in paths

    schema_text = str(spec["components"]["schemas"])
    assert "chat_history" not in schema_text


def test_knowledge_qa_requests_reject_frontend_supplied_chat_history() -> None:
    from app.schemas.knowledge import KnowledgeQARequest
    from app.schemas.knowledge_studio import KnowledgeStudioQaRequest

    with pytest.raises(ValidationError):
        KnowledgeQARequest(
            question="刚才我问的是什么？",
            dataset_ids=["kb-demo"],
            chat_history=[{"role": "user", "content": "旧历史"}],
        )

    with pytest.raises(ValidationError):
        KnowledgeStudioQaRequest(
            session_id="sess-1",
            message="刚才我问的是什么？",
            chat_history=[{"role": "user", "content": "旧历史"}],
        )


@pytest.mark.asyncio
async def test_knowledge_studio_route_forwards_no_client_history(monkeypatch) -> None:
    from app.api.routes import knowledge_studio as route
    from app.schemas.knowledge_studio import KnowledgeStudioQaRequest

    class DummyKnowledgeService:
        def ensure_exists(self, kb_id: str) -> None:
            return None

    captured = {}

    async def fake_resolve(*_args, **_kwargs):
        return object()

    async def fake_process(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(route, "resolve_qa_llm_with_db_fallback", fake_resolve)
    monkeypatch.setattr(route, "process_knowledge_studio_assistant_stream", fake_process)

    response = await route.kb_studio_chat_qa(
        "kb-demo",
        KnowledgeStudioQaRequest(
            session_id="sess-1",
            message="刚才我问的是什么？",
        ),
        DummyKnowledgeService(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        "tenant-a",
    )
    async for _chunk in response.body_iterator:
        pass

    assert "chat_history" not in captured["kwargs"]

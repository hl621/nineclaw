"""Route-level tests for knowledge-base name-uniqueness.

The knowledge backend (RAGFlow / filesystem) is mocked so the tests run
without an external dependency. The duplicate-name guard lives in the
``POST /v1/knowledge`` route and must return 409 when an existing KB
with the same name is found via ``list_knowledge``.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import knowledge as knowledge_route
from app.main import app


class _FakeBackend:
    """Minimal stand-in for the KnowledgeBackend union."""

    def __init__(self, existing_names, created_record=None):
        self._existing = [{"name": n, "id": n} for n in existing_names]
        self.created_record = created_record or {
            "id": "new-id",
            "name": "fresh",
            "description": "",
            "group": "",
            "owner": "",
            "serial": None,
            "status": "success",
            "doc_count": 0,
            "updated_at": datetime.now(timezone.utc),
        }
        self.create_called = False

    def list_knowledge(self):
        return list(self._existing)

    def create_knowledge(self, body):
        self.create_called = True
        return self.created_record


@pytest.mark.asyncio
async def test_create_knowledge_rejects_duplicate_name():
    backend = _FakeBackend(existing_names=["dup"])
    app.dependency_overrides[knowledge_route.get_knowledge_service_dep] = lambda: backend
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post(
                "/v1/knowledge",
                json={"name": "dup"},
            )
        assert resp.status_code == 409
        assert "dup" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
    assert not backend.create_called, "create must not be called on conflict"


@pytest.mark.asyncio
async def test_create_knowledge_allows_free_name():
    backend = _FakeBackend(existing_names=["other"])
    app.dependency_overrides[knowledge_route.get_knowledge_service_dep] = lambda: backend
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post(
                "/v1/knowledge",
                json={"name": "fresh"},
            )
        assert resp.status_code == 201
        assert resp.json()["data"]["name"] == "fresh"
    finally:
        app.dependency_overrides.clear()
    assert backend.create_called


@pytest.mark.asyncio
async def test_create_knowledge_list_failure_does_not_block_create():
    # If the pre-check list_knowledge errors, the route must fall back to
    # allowing the call rather than masking the real backend error.
    backend = MagicMock()
    backend.list_knowledge.side_effect = RuntimeError("ragflow down")
    backend.create_knowledge.return_value = {
        "id": "new-id",
        "name": "fresh",
        "description": "",
        "group": "",
        "owner": "",
        "serial": None,
        "status": "success",
        "doc_count": 0,
        "updated_at": datetime.now(timezone.utc),
    }
    app.dependency_overrides[knowledge_route.get_knowledge_service_dep] = lambda: backend
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post("/v1/knowledge", json={"name": "fresh"})
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.clear()
    backend.create_knowledge.assert_called_once()

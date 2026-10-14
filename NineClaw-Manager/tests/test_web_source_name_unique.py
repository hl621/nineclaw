"""Route-level tests for WebSource name-uniqueness (tenant-scoped).

Overrides the session dependency with an in-memory mock so the tests
run without a live Postgres. Verifies the 409 guard added with the
uq_web_sources_tenant_name unique constraint.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import web_sources as web_sources_route
from app.db.session import get_session
from app.main import app
from app.models.web_source import WebSource


class _SessionMock:
    """Mock session whose execute() resolves to staged scalars."""

    def __init__(self, scalars_per_call):
        self._results = []
        for value in scalars_per_call:
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=value)
            self._results.append(result)
        self.execute = AsyncMock(side_effect=self._results)
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.delete = AsyncMock()


@pytest.mark.asyncio
async def test_create_web_source_rejects_duplicate_name():
    session = _SessionMock([WebSource(name="dup", tenant_id="default")])

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[web_sources_route.get_tenant_id] = lambda: "default"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post("/v1/web-sources", json={"name": "dup", "url": ""})
        assert resp.status_code == 409
        assert "dup" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
    # Must not have staged a new row.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_web_source_allows_free_name():
    session = _SessionMock([None])
    created = WebSource(
        id=uuid.uuid4(),
        tenant_id="default",
        name="fresh",
        url="",
        url_base="",
        type="other",
        description="",
        enabled=True,
        is_verified=False,
        request_config=None,
        extractor_code=None,
    )

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[web_sources_route.get_tenant_id] = lambda: "default"
    # refresh returns the persisted object.
    session.refresh = AsyncMock(return_value=created)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post("/v1/web-sources", json={"name": "fresh", "url": ""})
        assert resp.status_code == 201
        assert resp.json()["name"] == "fresh"
    finally:
        app.dependency_overrides.clear()

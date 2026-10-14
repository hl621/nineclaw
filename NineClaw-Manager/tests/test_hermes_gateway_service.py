"""Hermes gateway request-contract tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.hermes_gateway_service import HermesGatewayService


@pytest.mark.asyncio
async def test_create_run_uses_hermes_input_contract(monkeypatch):
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(202, json={"run_id": "hermes-1"})

    original_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    async with HermesGatewayService("http://hermes", "gateway-token") as gateway:
        result = await gateway.create_run(
            [{"role": "user", "content": "hello"}],
            instructions="manager-only context",
            session_id="execution-1",
        )

    assert result == {"run_id": "hermes-1"}
    assert captured["path"] == "/v1/runs"
    assert captured["body"] == {
        "model": "hermes-agent",
        "input": [{"role": "user", "content": "hello"}],
        "instructions": "manager-only context",
        "session_id": "execution-1",
    }

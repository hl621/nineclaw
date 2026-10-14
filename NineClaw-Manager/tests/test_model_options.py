"""Contract tests for config-backed Manager model options."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes.instances import get_manager_model_options
from app.services.hermes_dashboard_service import HermesError
from app.services.model_options_service import build_model_options_from_config


class _Dashboard:
    instances = []
    response = {}
    failure = None

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.calls = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_config(self):
        self.calls.append("config")
        if self.failure:
            raise self.failure
        return self.response


def test_formatter_returns_only_custom_providers_and_enabled_moa():
    payload = build_model_options_from_config(
        {
            "model": "deepseek-v4-pro",
            "custom_providers": [
                {
                    "name": "DeepSeek",
                    "base_url": "https://secret.example/v1",
                    "api_key": "must-not-leak",
                    "models": {
                        "deepseek-v4-pro": {},
                        "deepseek-v4-flash": {"api_key": "also-secret"},
                    },
                },
                {"name": "模型栈", "models": ["Baichuan-M2"]},
            ],
            "moa": {
                "presets": {
                    "default": {"enabled": True},
                    "fast": {"enabled": True},
                    "disabled": {"enabled": False},
                }
            },
            "providers": {"openrouter": {"api_key": "not-returned"}},
        }
    )

    assert list(payload) == ["groups"]
    assert [group["provider_id"] for group in payload["groups"]] == [
        "custom:deepseek",
        "custom:模型栈",
        "moa",
    ]
    assert [model["id"] for model in payload["groups"][0]["models"]] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert [model["id"] for model in payload["groups"][2]["models"]] == [
        "default",
        "fast",
    ]
    assert "must-not-leak" not in str(payload)
    assert "openrouter" not in str(payload)


@pytest.mark.asyncio
async def test_route_checks_tenant_and_formats_dashboard_config(monkeypatch):
    from app.services import hermes_dashboard_service

    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id="instance-1", tenant_id="tenant-a")
    _Dashboard.instances = []
    _Dashboard.failure = None
    _Dashboard.response = {
        "model": "m1",
        "custom_providers": [{"name": "Provider One", "models": {"m1": {}}}],
        "moa": {"presets": {"default": {"enabled": True}}},
    }
    monkeypatch.setattr(hermes_dashboard_service, "HermesService", _Dashboard)

    response = await get_manager_model_options(
        "instance-1",
        profile="ignored",
        refresh=True,
        tenant_id="tenant-a",
        session=session,
    )

    assert list(response.data) == ["groups"]
    assert [group["provider_id"] for group in response.data["groups"]] == [
        "custom:provider-one",
        "moa",
    ]
    assert _Dashboard.instances[0].calls == ["config"]
    scalar_query = str(session.scalar.await_args.args[0])
    assert "service_instances.id" in scalar_query
    assert "service_instances.tenant_id" in scalar_query


@pytest.mark.asyncio
async def test_cross_tenant_instance_returns_404_before_dashboard_access(monkeypatch):
    from app.services import hermes_dashboard_service

    session = AsyncMock()
    session.scalar.return_value = None
    _Dashboard.instances = []
    monkeypatch.setattr(hermes_dashboard_service, "HermesService", _Dashboard)

    with pytest.raises(HTTPException) as exc_info:
        await get_manager_model_options("other-instance", tenant_id="tenant-a", session=session)

    assert exc_info.value.status_code == 404
    assert _Dashboard.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (httpx.ReadTimeout("slow"), 504),
        (httpx.ConnectError("offline"), 502),
        (HermesError(500, "token=must-not-leak"), 502),
    ],
)
async def test_dashboard_failures_are_mapped(monkeypatch, failure, expected_status):
    from app.services import hermes_dashboard_service

    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id="instance-1", tenant_id="tenant-a")
    _Dashboard.instances = []
    _Dashboard.failure = failure
    monkeypatch.setattr(hermes_dashboard_service, "HermesService", _Dashboard)

    with pytest.raises(HTTPException) as exc_info:
        await get_manager_model_options("instance-1", tenant_id="tenant-a", session=session)

    assert exc_info.value.status_code == expected_status
    assert "must-not-leak" not in str(exc_info.value.detail)
    _Dashboard.failure = None


@pytest.mark.asyncio
async def test_invalid_config_is_mapped_to_bad_gateway(monkeypatch):
    from app.services import hermes_dashboard_service

    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(id="instance-1", tenant_id="tenant-a")
    _Dashboard.instances = []
    _Dashboard.failure = None
    _Dashboard.response = {"custom_providers": {"not": "a-list"}}
    monkeypatch.setattr(hermes_dashboard_service, "HermesService", _Dashboard)

    with pytest.raises(HTTPException) as exc_info:
        await get_manager_model_options("instance-1", tenant_id="tenant-a", session=session)

    assert exc_info.value.status_code == 502

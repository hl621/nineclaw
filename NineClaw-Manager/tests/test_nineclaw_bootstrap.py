"""Tests for post-create NineClaw bootstrap sequencing."""

import pytest

from app.core.config import settings
from app.services import nineclaw_bootstrap


@pytest.mark.asyncio
async def test_bootstrap_waits_for_dashboard_even_without_default_config(monkeypatch) -> None:
    calls: list[str] = []

    class FakeHermesService:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_status(self):
            calls.append("status")
            return {"ok": True}

        async def put_env(self, key: str, value: str):
            calls.append(f"env:{key}")

        async def put_config(self, config):
            calls.append("config")

        async def restart_gateway(self):
            calls.append("restart")

    monkeypatch.setattr(settings, "nineclaw_default_env", {})
    monkeypatch.setattr(settings, "nineclaw_default_config", {})
    monkeypatch.setattr(settings, "nineclaw_custom_provider_name", "")
    monkeypatch.setattr(settings, "nineclaw_custom_provider_base_url", "")
    monkeypatch.setattr(settings, "nineclaw_custom_provider_api_key", "")
    monkeypatch.setattr(settings, "nineclaw_custom_provider_model", "")
    monkeypatch.setattr(nineclaw_bootstrap, "HermesService", FakeHermesService)

    await nineclaw_bootstrap.bootstrap_instance("inst-ready")

    assert calls == ["status"]

"""Unit tests for Hermes dashboard client helpers."""

import pytest

from app.services.hermes_dashboard_service import HermesService


@pytest.mark.asyncio
async def test_wait_action_finished_polls_until_not_running(monkeypatch):
    svc = HermesService(base_url="http://example.test", api_key="token")
    statuses = [
        {"name": "gateway-restart", "running": True, "exit_code": None},
        {"name": "gateway-restart", "running": False, "exit_code": 0},
    ]

    async def fake_get_action_status(name: str, lines: int = 200):
        return statuses.pop(0)

    async def fake_sleep(_: float):
        return None

    monkeypatch.setattr(svc, "get_action_status", fake_get_action_status)
    monkeypatch.setattr("app.services.hermes_dashboard_service.asyncio.sleep", fake_sleep)

    result = await svc.wait_action_finished("gateway-restart", poll_interval=0.01)

    assert result == {"name": "gateway-restart", "running": False, "exit_code": 0}
    assert statuses == []


@pytest.mark.asyncio
async def test_wait_action_finished_times_out(monkeypatch):
    svc = HermesService(base_url="http://example.test", api_key="token")

    async def fake_get_action_status(name: str, lines: int = 200):
        return {"name": name, "running": True, "exit_code": None}

    async def fake_sleep(_: float):
        return None

    monkeypatch.setattr(svc, "get_action_status", fake_get_action_status)
    monkeypatch.setattr("app.services.hermes_dashboard_service.asyncio.sleep", fake_sleep)

    with pytest.raises(TimeoutError):
        await svc.wait_action_finished("gateway-restart", timeout=0, poll_interval=0.01)

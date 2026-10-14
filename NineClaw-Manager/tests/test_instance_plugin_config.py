"""Unit tests for instance plugin config helpers."""

from __future__ import annotations

import asyncio

import pytest

from app.services import instance_plugin_config_service
from app.services.hermes_dashboard_service import HermesError
from app.services.instance_plugin_config_service import (
    knowledge_ids_from_config,
    knowledge_ids_from_qyrag_datasets,
    plugin_enabled_from_hub,
    read_instance_rag_config,
    source_ids_from_include_sources,
)
from app.services.knowledge_deploy_service import build_rag_deploy_env


def test_knowledge_ids_from_config() -> None:
    assert knowledge_ids_from_config(
        {"external_knowledge": {"dataset_ids": ["a", "b", "a", ""]}}
    ) == ["a", "b"]


def test_knowledge_ids_from_qyrag_datasets() -> None:
    raw = '{"\\u653f\\u7b56\\u5e93": "kb-a", "kb-b": "kb-b"}'
    assert knowledge_ids_from_qyrag_datasets(raw) == ["kb-a", "kb-b"]


def test_source_ids_from_include_sources() -> None:
    assert source_ids_from_include_sources("bing, baidu_news,,bing") == [
        "bing",
        "baidu_news",
    ]


def test_plugin_enabled_from_hub() -> None:
    hub = {
        "agent_plugins": [
            {"name": "NineClaw-QYRAG", "enabled": True},
            {"id": "NineClaw-WebSearch", "status": "disabled"},
        ]
    }
    assert plugin_enabled_from_hub(hub, "NineClaw-QYRAG") is True
    assert plugin_enabled_from_hub(hub, "NineClaw-WebSearch") is False
    assert plugin_enabled_from_hub(hub, "missing") is None


def test_plugin_enabled_from_hub_real_runtime_status_shape() -> None:
    """Regression: live Hermes hub reports ``runtime_status`` on ``plugins``
    nodes, not ``enabled``/``status`` — the toggle state must be read from it.
    """
    hub = {
        "plugins": [
            {"name": "NineClaw-QYRAG", "runtime_status": "disabled", "source": "user"},
            {"name": "NineClaw-WebSearch", "runtime_status": "enabled", "source": "user"},
            {"name": "web-tavily", "runtime_status": "inactive", "source": "bundled"},
        ]
    }
    assert plugin_enabled_from_hub(hub, "NineClaw-QYRAG") is False
    assert plugin_enabled_from_hub(hub, "NineClaw-WebSearch") is True
    assert plugin_enabled_from_hub(hub, "web-tavily") is False


def test_build_rag_deploy_env_can_clear_datasets() -> None:
    env = build_rag_deploy_env(
        base_url="http://rag",
        api_key="k",
        knowledge_ids=[],
        always_include_datasets=True,
    )
    assert env["QYRAG_DATASETS"] == "{}"


@pytest.mark.asyncio
async def test_read_rag_config_fetches_dashboard_inputs_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: set[str] = set()
    all_started = asyncio.Event()
    release = asyncio.Event()

    class FakeHermesService:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def _result(self, name: str, value: object) -> object:
            started.add(name)
            if len(started) == 3:
                all_started.set()
            await release.wait()
            return value

        async def get_config(self):
            return await self._result(
                "config", {"external_knowledge": {"dataset_ids": ["kb-1"]}}
            )

        async def get_env(self):
            return await self._result("env", {})

        async def get_plugins_hub(self):
            return await self._result(
                "hub", {"agent_plugins": [{"name": "NineClaw-QYRAG", "enabled": False}]}
            )

    monkeypatch.setattr(
        instance_plugin_config_service, "HermesService", FakeHermesService
    )

    task = asyncio.create_task(read_instance_rag_config("instance-1"))
    await asyncio.wait_for(all_started.wait(), timeout=0.5)
    assert started == {"config", "env", "hub"}
    release.set()

    assert await task == {
        "enabled": False,
        "plugin_id": "NineClaw-QYRAG",
        "knowledge_ids": ["kb-1"],
        "plugin_status_known": True,
    }


@pytest.mark.asyncio
async def test_read_rag_config_only_degrades_plugins_hub_hermes_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHermesService:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_config(self):
            return {"external_knowledge": {"dataset_ids": ["kb-1"]}}

        async def get_env(self):
            return {}

        async def get_plugins_hub(self):
            raise HermesError(status_code=503, detail="unavailable")

    monkeypatch.setattr(
        instance_plugin_config_service, "HermesService", FakeHermesService
    )

    result = await read_instance_rag_config("instance-1")

    assert result["knowledge_ids"] == ["kb-1"]
    assert result["enabled"] is True
    assert result["plugin_status_known"] is False


@pytest.mark.asyncio
async def test_read_rag_config_propagates_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHermesService:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_config(self):
            raise HermesError(status_code=500, detail="config failed")

        async def get_env(self):
            return {}

        async def get_plugins_hub(self):
            return {}

    monkeypatch.setattr(
        instance_plugin_config_service, "HermesService", FakeHermesService
    )

    with pytest.raises(HermesError, match="config failed"):
        await read_instance_rag_config("instance-1")

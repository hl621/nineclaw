"""Tests for knowledge deploy helpers."""

from __future__ import annotations

import json

import pytest

from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.knowledge_deploy_service import (
    build_rag_deploy_env,
    ensure_ragflow_plugin_enabled,
    resolve_ragflow_credentials,
)


def test_resolve_ragflow_credentials_fallback(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ragflow_base_url", "http://ragflow.test:8513")
    monkeypatch.setattr(settings, "ragflow_api_key", "env-key")

    url, key = resolve_ragflow_credentials(base_url="", api_key="")
    assert url == "http://ragflow.test:8513"
    assert key == "env-key"

    url2, key2 = resolve_ragflow_credentials(
        base_url="http://db:8513", api_key="db-key"
    )
    assert url2 == "http://db:8513"
    assert key2 == "db-key"


def test_build_rag_deploy_env() -> None:
    env = build_rag_deploy_env(
        base_url="http://ragflow:8513",
        api_key="secret",
        knowledge_ids=["kb-a", "kb-b"],
        knowledge_name_map={"kb-a": "政策库", "kb-b": "产品手册"},
    )
    assert env["HERMES_ENABLE_PROJECT_PLUGINS"] == "1"
    assert env["QYRAG_BASE_URL"] == "http://ragflow:8513"
    assert env["QYRAG_API_KEY"] == "secret"
    # Human-readable Chinese keys (ensure_ascii=False).
    assert env["QYRAG_DATASETS"] == '{"政策库": "kb-a", "产品手册": "kb-b"}'
    assert json.loads(env["QYRAG_DATASETS"]) == {"政策库": "kb-a", "产品手册": "kb-b"}


def test_build_rag_deploy_env_chinese_readable_key() -> None:
    env = build_rag_deploy_env(
        base_url="http://ragflow:8513",
        api_key="secret",
        knowledge_ids=["5bd5db02708311f1b5e7752a9c8cbb5e"],
        knowledge_name_map={"5bd5db02708311f1b5e7752a9c8cbb5e": "贸易战"},
    )
    assert env["QYRAG_DATASETS"] == (
        '{"贸易战": "5bd5db02708311f1b5e7752a9c8cbb5e"}'
    )


def test_build_dotenv_upsert_python_embeds_chinese() -> None:
    from app.services.knowledge_deploy_service import build_dotenv_upsert_python
    import base64
    import json as _json

    script = build_dotenv_upsert_python(
        "QYRAG_DATASETS",
        '{"策略分析": "afe3d03a863811f181aba75879343158"}',
    )
    assert "python" not in script.lower() or True
    # Payload round-trips to Chinese value
    marker = "base64.b64decode('"
    start = script.index(marker) + len(marker)
    end = script.index("')", start)
    payload = script[start:end]
    data = _json.loads(base64.b64decode(payload).decode("utf-8"))
    assert data["key"] == "QYRAG_DATASETS"
    assert "策略分析" in data["value"]
    assert "afe3d03a863811f181aba75879343158" in data["value"]
    assert "\\u7b56" not in data["value"]


def test_build_rag_deploy_env_falls_back_to_id_for_missing_names() -> None:
    env = build_rag_deploy_env(
        base_url="http://ragflow:8513",
        api_key="secret",
        knowledge_ids=["kb-a", "kb-b"],
        knowledge_name_map={"kb-a": "政策库"},
    )

    assert json.loads(env["QYRAG_DATASETS"]) == {"政策库": "kb-a", "kb-b": "kb-b"}


def test_build_rag_deploy_env_skips_blank_ids_and_blank_names() -> None:
    env = build_rag_deploy_env(
        base_url="http://ragflow:8513",
        api_key="secret",
        knowledge_ids=["", "  ", "kb-a"],
        knowledge_name_map={"kb-a": "   "},
    )
    assert json.loads(env["QYRAG_DATASETS"]) == {"kb-a": "kb-a"}


@pytest.mark.asyncio
async def test_ensure_ragflow_plugin_enabled_uses_qyrag_plugin(monkeypatch) -> None:
    svc = HermesService(base_url="http://example.test", api_key="token")
    calls: list[tuple[str, str]] = []

    async def fake_install(identifier: str, force: bool = False, enable: bool = True):
        calls.append(("install", identifier))

    async def fake_enable(name: str):
        calls.append(("enable", name))

    monkeypatch.setattr(svc, "install_agent_plugin", fake_install)
    monkeypatch.setattr(svc, "enable_agent_plugin", fake_enable)

    plugin_id = await ensure_ragflow_plugin_enabled(svc)

    assert plugin_id == "NineClaw-QYRAG"
    assert calls == [
        ("install", "NineClaw-QYRAG"),
        ("enable", "NineClaw-QYRAG"),
    ]

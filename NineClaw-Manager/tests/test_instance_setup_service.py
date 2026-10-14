from types import SimpleNamespace

import pytest

from app.services import instance_setup_service
from app.services.instance_setup_service import (
    _build_custom_provider_entry,
    _build_hermes_mcp_entry,
    _build_model_setup,
    _extract_supported_auxiliary_tasks,
    _normalize_stdio_args,
    has_initial_setup,
    summarize_initial_setup,
)


def test_initial_setup_custom_provider_disables_live_discovery() -> None:
    entry = _build_custom_provider_entry(
        SimpleNamespace(
            name="modelstack",
            base_url="http://modelstack/v1",
            models=["gpt-5", "claude-sonnet"],
            api_key="secret",
        )
    )

    assert entry == {
        "name": "modelstack",
        "base_url": "http://modelstack/v1",
        "models": {"gpt-5": {}, "claude-sonnet": {}},
        "discover_models": False,
        "api_key": "secret",
    }


def test_initial_setup_empty_custom_provider_keeps_live_discovery() -> None:
    entry = _build_custom_provider_entry(
        SimpleNamespace(
            name="empty",
            base_url="http://empty/v1",
            models=[],
            api_key=None,
        )
    )

    assert "discover_models" not in entry


@pytest.mark.asyncio
async def test_initial_setup_model_payload_disables_live_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        id="provider-1",
        name="modelstack",
        base_url="http://modelstack/v1",
        models=["gpt-5"],
        api_key=None,
    )

    async def fake_get_providers(*_: object):
        return [provider]

    monkeypatch.setattr(instance_setup_service, "_get_providers", fake_get_providers)

    config, main, auxiliary = await _build_model_setup(
        None,
        "tenant-1",
        SimpleNamespace(provider_ids=["provider-1"]),
    )

    assert config["custom_providers"] == [
        {
            "name": "modelstack",
            "base_url": "http://modelstack/v1",
            "models": {"gpt-5": {}},
            "discover_models": False,
        }
    ]
    assert main is None
    assert auxiliary == []


def test_has_initial_setup_false_for_empty_payload() -> None:
    assert has_initial_setup(None) is False
    assert has_initial_setup(SimpleNamespace()) is False
    assert has_initial_setup(SimpleNamespace(provider_ids=[], skill_slugs=[])) is False


def test_has_initial_setup_true_for_selected_resources() -> None:
    assert has_initial_setup(SimpleNamespace(provider_ids=["p1"])) is True
    assert has_initial_setup(SimpleNamespace(skill_slugs=["demo"])) is True
    assert has_initial_setup(SimpleNamespace(web_source_ids=["source"])) is True


def test_summarize_initial_setup_counts_selected_resources() -> None:
    setup = SimpleNamespace(
        provider_ids=["p1"],
        main_model=SimpleNamespace(provider="openai", model="gpt-4.1"),
        auxiliary_models=[SimpleNamespace(task="vision")],
        skill_slugs=["a", "b"],
        mcp_ids=[],
        knowledge_ids=["kb"],
        web_source_ids=["google"],
    )

    assert summarize_initial_setup(setup) == {
        "provider_count": 1,
        "main_model": {"provider": "openai", "model": "gpt-4.1"},
        "auxiliary_model_count": 1,
        "skill_count": 2,
        "mcp_count": 0,
        "knowledge_count": 1,
        "web_source_count": 1,
    }


def test_initial_setup_mcp_url_entry_matches_deploy_shape() -> None:
    entry = _build_hermes_mcp_entry(
        SimpleNamespace(
            transport="url",
            url="https://mcp.example.com/mcp",
            headers={},
            timeout=None,
            connect_timeout=None,
            enabled=True,
            tools=None,
            tool_settings=None,
        )
    )

    assert entry == {
        "url": "https://mcp.example.com/mcp",
        "sampling": {"enabled": False},
    }


def test_initial_setup_stdio_args_match_deploy_normalization() -> None:
    assert _normalize_stdio_args(['--label "foo bar"', "--enabled"]) == [
        "--label",
        "foo bar",
        "--enabled",
    ]


def test_extract_supported_auxiliary_tasks() -> None:
    assert _extract_supported_auxiliary_tasks(
        {"tasks": [{"task": "vision"}, {"task": "mcp"}, {"name": "invalid"}]}
    ) == {"vision", "mcp"}

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.models.instance import ServiceInstance
from app.services import instance_setup_service
from app.services.instance_agent_snapshot import (
    InstanceAgentSnapshotNotFoundError,
    extract_provider_snapshot_from_hermes_config,
    merge_manager_resource_snapshot,
    persist_manager_resource_snapshot,
    read_instance_provider_snapshot,
    read_manager_resource_snapshot,
)


_TEMPLATE_ID = UUID("00000000-0000-0000-0000-000000000000")


def _instance(config: dict | None = None) -> ServiceInstance:
    return ServiceInstance(
        id="instance-1",
        tenant_id="tenant-1",
        template_id=_TEMPLATE_ID,
        name="agent-1",
        config=config or {},
    )


def test_legacy_instance_snapshot_is_unknown_without_hermes_inference() -> None:
    snapshot = read_manager_resource_snapshot({"model": {"api_key": "secret"}})
    malformed_snapshot = read_manager_resource_snapshot(
        {"manager_resource_snapshot": {"model": {"provider": "openai"}}}
    )

    assert snapshot == {
        "snapshot_state": "unknown",
        "model": None,
        "knowledge_bases": [],
        "mcps": [],
        "skills": [],
        "config_updated_at": None,
    }
    assert malformed_snapshot["snapshot_state"] == "unknown"


def test_snapshot_merge_preserves_known_resources_and_strips_secrets() -> None:
    original = {
        "runtime_config": {"api_key": "runtime-secret"},
        "manager_resource_snapshot": {
            "model": {
                "provider": "legacy-provider",
                "model": "legacy-model",
                "api_key": "must-not-survive",
            },
            "knowledge_bases": [{"id": "kb-old", "name": "旧知识库"}],
            "mcps": [
                {
                    "id": "mcp-old",
                    "name": "旧 MCP",
                    "enabled": True,
                    "headers": {"Authorization": "must-not-survive"},
                }
            ],
            "skills": [{"slug": "writer", "name": "旧写作"}],
            "config_updated_at": "2026-01-01T00:00:00Z",
        },
    }

    merged = merge_manager_resource_snapshot(
        original,
        model={
            "provider": "openai",
            "model": "gpt-5",
            "api_key": "must-not-survive",
        },
        knowledge_bases=[
            {
                "id": "kb-new",
                "name": "新知识库",
                "base_url": "https://private.example",
            }
        ],
        mcps=[
            {
                "id": "mcp-old",
                "name": "新 MCP 名称",
                "enabled": False,
                "headers": {"Authorization": "must-not-survive"},
            },
            {"id": "mcp-new", "name": "新增 MCP", "enabled": True},
        ],
        skills=[
            {"slug": "writer", "name": "新写作", "metadata": {"secret": "x"}},
            {"slug": "research", "name": "研究"},
        ],
        updated_at=datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )

    assert (
        original["manager_resource_snapshot"]["model"]["api_key"] == "must-not-survive"
    )
    assert merged["runtime_config"] == {"api_key": "runtime-secret"}
    assert merged["manager_resource_snapshot"] == {
        "model": {"provider": "openai", "model": "gpt-5"},
        "knowledge_bases": [{"id": "kb-new", "name": "新知识库"}],
        "mcps": [
            {"id": "mcp-old", "name": "新 MCP 名称", "enabled": False},
            {"id": "mcp-new", "name": "新增 MCP", "enabled": True},
        ],
        "skills": [
            {"slug": "writer", "name": "新写作"},
            {"slug": "research", "name": "研究"},
        ],
        "config_updated_at": "2026-07-22T08:00:00Z",
    }


def test_snapshot_merge_retains_untouched_resource_categories() -> None:
    first = merge_manager_resource_snapshot(
        {},
        mcps=[{"id": "mcp-1", "name": "MCP 1", "enabled": True}],
        updated_at=datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )
    second = merge_manager_resource_snapshot(
        first,
        skills=[{"slug": "writer", "name": "写作"}],
        updated_at=datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc),
    )

    assert second["manager_resource_snapshot"]["mcps"] == [
        {"id": "mcp-1", "name": "MCP 1", "enabled": True}
    ]
    assert second["manager_resource_snapshot"]["skills"] == [
        {"slug": "writer", "name": "写作"}
    ]
    assert second["manager_resource_snapshot"]["knowledge_bases"] == []


def test_provider_snapshot_distinguishes_legacy_from_explicit_empty() -> None:
    legacy = merge_manager_resource_snapshot(
        {},
        skills=[{"slug": "writer", "name": "写作"}],
    )
    explicit_empty = merge_manager_resource_snapshot(legacy, providers=[])

    assert read_instance_provider_snapshot(legacy) is None
    assert read_instance_provider_snapshot(explicit_empty) == []


def test_snapshot_merge_rejects_malformed_existing_providers() -> None:
    with pytest.raises(ValueError, match="Provider snapshot must be a list"):
        merge_manager_resource_snapshot(
            {"manager_resource_snapshot": {"providers": None}},
            skills=[{"slug": "writer", "name": "写作"}],
        )


def test_provider_snapshot_is_normalized_and_secret_free() -> None:
    providers = extract_provider_snapshot_from_hermes_config(
        {
            "custom_providers": [
                {
                    "name": " custom ",
                    "base_url": "https://private.example/v1",
                    "api_key": "must-not-survive",
                    "models": {" model-b ": {}, "model-a": {}},
                },
                {"name": "CUSTOM", "models": ["model-c", "model-a"]},
            ]
        }
    )

    assert providers == [
        {"name": "custom", "models": ["model-a", "model-b", "model-c"]}
    ]
    assert "private.example" not in repr(providers)
    assert "must-not-survive" not in repr(providers)


@pytest.mark.parametrize(
    "providers",
    [
        {},
        ["not-an-object"],
        [{"models": []}],
        [{"name": "custom"}],
        [{"name": "custom", "models": "model-1"}],
        [{"name": "custom", "models": [None]}],
    ],
)
def test_provider_snapshot_rejects_malformed_shapes(providers) -> None:
    with pytest.raises(ValueError):
        extract_provider_snapshot_from_hermes_config({"custom_providers": providers})


@pytest.mark.asyncio
async def test_persist_snapshot_scopes_lookup_by_tenant_and_locks_instance() -> None:
    instance = _instance({"unrelated": {"keep": True}})
    result = MagicMock()
    result.scalar_one_or_none.return_value = instance
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    saved = await persist_manager_resource_snapshot(
        session,
        tenant_id="tenant-1",
        instance_id="instance-1",
        model={"provider": "openai", "model": "gpt-5"},
    )

    assert saved is instance
    assert instance.config["unrelated"] == {"keep": True}
    assert instance.config["manager_resource_snapshot"]["model"] == {
        "provider": "openai",
        "model": "gpt-5",
    }
    assert session.execute.await_count == 1
    assert "FOR UPDATE" in str(session.execute.await_args.args[0])
    session.add.assert_called_once_with(instance)


@pytest.mark.asyncio
async def test_persist_snapshot_rejects_missing_or_cross_tenant_instance() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(InstanceAgentSnapshotNotFoundError):
        await persist_manager_resource_snapshot(
            session,
            tenant_id="tenant-1",
            instance_id="missing",
            skills=[{"slug": "writer", "name": "写作"}],
        )


@pytest.mark.asyncio
async def test_initial_setup_records_each_successfully_configured_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHermesService:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, config):
            return None

        async def put_env(self, key, value):
            return None

        async def set_model_assignment(self, **kwargs):
            return None

    persist = AsyncMock()
    monkeypatch.setattr(
        instance_setup_service,
        "HermesService",
        lambda **kwargs: FakeHermesService(),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "_build_model_setup",
        AsyncMock(
            return_value=(
                {
                    "custom_providers": [
                        {
                            "name": "openai",
                            "base_url": "https://private.example/v1",
                            "api_key": "must-not-leak",
                            "models": {"gpt-5": {}},
                        }
                    ]
                },
                ("openai", "gpt-5"),
                [],
            )
        ),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "_build_mcp_entries",
        AsyncMock(
            return_value=(
                {"MCP 1": {"url": "https://mcp.example"}},
                [{"id": "mcp-1", "name": "MCP 1", "enabled": True}],
            )
        ),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "_build_knowledge_setup",
        AsyncMock(
            return_value=(
                {"external_knowledge": {"dataset_ids": ["kb-1"]}},
                {"RAGFLOW_DATASET_IDS": "kb-1"},
                [{"id": "kb-1", "name": "知识库 1"}],
            )
        ),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "ensure_ragflow_plugin_enabled",
        AsyncMock(),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "_copy_skills_to_container",
        AsyncMock(return_value=[{"slug": "writer", "name": "写作"}]),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "persist_manager_resource_snapshot",
        persist,
    )

    setup = SimpleNamespace(
        provider_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        main_model=SimpleNamespace(provider="openai", model="gpt-5"),
        auxiliary_models=[],
        mcp_ids=[UUID("00000000-0000-0000-0000-000000000002")],
        mcp_tools_config=None,
        knowledge_ids=["kb-1"],
        skill_slugs=["writer"],
        web_source_ids=[],
    )

    should_restart = await instance_setup_service.apply_initial_setup(
        instance_id="instance-1",
        tenant_id="tenant-1",
        setup=setup,
        session=MagicMock(),
    )

    assert should_restart is True
    assert [call.kwargs for call in persist.await_args_list] == [
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "providers": [{"name": "openai", "models": ["gpt-5"]}],
        },
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "mcps": [{"id": "mcp-1", "name": "MCP 1", "enabled": True}],
        },
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "model": {"provider": "openai", "model": "gpt-5"},
        },
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "knowledge_bases": [{"id": "kb-1", "name": "知识库 1"}],
        },
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "skills": [{"slug": "writer", "name": "写作"}],
        },
    ]


@pytest.mark.asyncio
async def test_initial_setup_without_model_records_explicit_empty_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHermesService:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, _config):
            return None

    persist = AsyncMock()
    monkeypatch.setattr(
        instance_setup_service,
        "HermesService",
        lambda **_kwargs: FakeHermesService(),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "_copy_skills_to_container",
        AsyncMock(return_value=[{"slug": "writer", "name": "写作"}]),
    )
    monkeypatch.setattr(
        instance_setup_service,
        "persist_manager_resource_snapshot",
        persist,
    )

    should_restart = await instance_setup_service.apply_initial_setup(
        instance_id="instance-1",
        tenant_id="tenant-1",
        setup=SimpleNamespace(
            provider_ids=[],
            main_model=None,
            auxiliary_models=[],
            mcp_ids=[],
            knowledge_ids=[],
            skill_slugs=["writer"],
            web_source_ids=[],
        ),
        session=MagicMock(),
    )

    assert should_restart is True
    assert [call.kwargs for call in persist.await_args_list] == [
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "providers": [],
        },
        {
            "tenant_id": "tenant-1",
            "instance_id": "instance-1",
            "skills": [{"slug": "writer", "name": "写作"}],
        },
    ]

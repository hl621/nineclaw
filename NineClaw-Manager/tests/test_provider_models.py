"""Provider model list normalization tests."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.api.routes import providers as provider_routes
from app.api.routes.providers import (
    _build_custom_provider_entry,
    _build_deploy_custom_providers,
    _extract_supported_auxiliary_tasks,
    _normalize_ragflow_model,
    _provider_endpoint,
    _rerank_upstream_urls,
    deploy_providers,
)
from app.schemas.provider import DeployRequest
from app.services.hermes_dashboard_service import HermesError


def test_deploy_custom_provider_disables_live_discovery():
    entries, name_index = _build_deploy_custom_providers(
        [
            SimpleNamespace(
                name="modelstack",
                base_url="http://modelstack/v1",
                models=["gpt-5"],
                api_key=None,
            )
        ]
    )

    assert entries == [
        {
            "name": "modelstack",
            "base_url": "http://modelstack/v1",
            "models": {"gpt-5": {}},
            "discover_models": False,
        }
    ]
    assert name_index[("modelstack", "gpt-5")]["model"] == "gpt-5"


def test_deploy_empty_custom_provider_keeps_live_discovery():
    entry = _build_custom_provider_entry(
        SimpleNamespace(
            name="empty",
            base_url="http://empty/v1",
            models=[],
            api_key=None,
        )
    )

    assert "discover_models" not in entry


def test_provider_endpoint_does_not_infer_v1_prefix():
    assert _provider_endpoint("http://model-server:8000", "models") == (
        "http://model-server:8000/models"
    )
    assert _provider_endpoint("http://model-server:8000/v1/", "/embeddings") == (
        "http://model-server:8000/v1/embeddings"
    )


def test_rerank_urls_do_not_infer_v1_prefix():
    assert _rerank_upstream_urls("https://api.example.com") == [
        "https://api.example.com/rerank",
        "https://api.example.com/p002/rerank",
    ]


def test_normalize_ragflow_model_preserves_model_id_for_submission():
    item = _normalize_ragflow_model(
        {
            "id": "BAAI/gte-rerank",
            "name": "gte-rerank",
            "provider_name": "BAAI",
            "model_type": ["rerank"],
        }
    )

    assert item is not None
    assert item["id"] == "BAAI/gte-rerank"
    assert item["name"] == "gte-rerank"


def test_normalize_ragflow_string_model_has_explicit_id():
    item = _normalize_ragflow_model("gte-rerank")

    assert item is not None
    assert item["id"] == "gte-rerank"


def test_extract_supported_auxiliary_tasks_ignores_unknown_shapes():
    payload = {
        "tasks": [
            {"task": "vision"},
            {"task": "compression", "provider": "auto"},
            {"task": ""},
            {"name": "session_search"},
            "bad",
        ],
    }

    assert _extract_supported_auxiliary_tasks(payload) == {"vision", "compression"}
    assert _extract_supported_auxiliary_tasks({"tasks": None}) == set()
    assert _extract_supported_auxiliary_tasks(None) == set()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_):
        return None


async def _consume_deploy_events(response):
    return [event async for event in response.body_iterator]


def _deploy_fixture_sessions():
    provider_id = UUID("00000000-0000-0000-0000-000000000001")
    provider = SimpleNamespace(
        id=provider_id,
        name="instance-provider",
        base_url="https://private.example/v1",
        models=["model-1"],
        api_key="secret",
    )
    instance = SimpleNamespace(
        id="instance-1",
        name="Agent 1",
        tenant_id="tenant-1",
        actual_state="running",
    )
    validation_session = MagicMock()
    validation_session.execute = AsyncMock(
        side_effect=[_Result([provider]), _Result([instance])]
    )
    snapshot_session = MagicMock()
    snapshot_session.commit = AsyncMock()
    return provider_id, validation_session, snapshot_session


@pytest.mark.asyncio
async def test_deploy_releases_instance_lock_before_non_running_event(monkeypatch):
    provider_id, validation_session, deployment_session = _deploy_fixture_sessions()
    deployment_session.rollback = AsyncMock()
    persist = AsyncMock()
    dashboard_factory = MagicMock()
    sessions = iter([validation_session, deployment_session])
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=SimpleNamespace(actual_state="stopped")),
    )
    monkeypatch.setattr(provider_routes, "HermesService", dashboard_factory)
    monkeypatch.setattr(provider_routes, "persist_manager_resource_snapshot", persist)

    response = await deploy_providers(
        DeployRequest(provider_ids=[provider_id], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)

    payload = " ".join(event["data"] for event in events)
    errors = [json.loads(event["data"]).get("error") for event in events]
    assert '"status": "failed"' in payload
    assert any("必须运行中才能部署" in error for error in errors if error)
    deployment_session.rollback.assert_awaited_once()
    dashboard_factory.assert_not_called()
    persist.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("providers", "current_custom_providers", "expected_snapshot"),
    [
        pytest.param(
            [
                SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    name="provider-1",
                    base_url="https://provider-1.example/v1",
                    models=["model-1", "model-2"],
                    api_key="secret-1",
                )
            ],
            [{"name": "provider-1", "models": {"model-1": {}}}],
            [{"name": "provider-1", "models": ["model-1", "model-2"]}],
            id="same-provider-model-update",
        ),
        pytest.param(
            [
                SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    name="provider-1",
                    base_url="https://provider-1.example/v1",
                    models=["model-1"],
                    api_key="secret-1",
                ),
                SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000002"),
                    name="provider-2",
                    base_url="https://provider-2.example/v1",
                    models=["model-2"],
                    api_key="secret-2",
                ),
            ],
            [{"name": "provider-1", "models": {"model-1": {}}}],
            [
                {"name": "provider-1", "models": ["model-1"]},
                {"name": "provider-2", "models": ["model-2"]},
            ],
            id="complete-provider-set-addition",
        ),
    ],
)
async def test_deploy_replaces_hermes_and_snapshot_with_complete_provider_set(
    monkeypatch,
    providers,
    current_custom_providers,
    expected_snapshot,
):
    instance = SimpleNamespace(
        id="instance-1",
        name="Agent 1",
        tenant_id="tenant-1",
        actual_state="running",
    )
    validation_session = MagicMock()
    validation_session.execute = AsyncMock(
        side_effect=[_Result(providers), _Result([instance])]
    )
    deployment_session = MagicMock()
    deployment_session.commit = AsyncMock()
    written_configs = []

    class Dashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {"custom_providers": current_custom_providers}

        async def put_config(self, config):
            written_configs.append(config)

        async def get_auxiliary_models(self):
            return {"tasks": []}

    sessions = iter([validation_session, deployment_session])
    persist = AsyncMock()
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(provider_routes, "HermesService", lambda **_kwargs: Dashboard())
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=instance),
    )
    monkeypatch.setattr(provider_routes, "persist_manager_resource_snapshot", persist)

    response = await deploy_providers(
        DeployRequest(
            provider_ids=[provider.id for provider in providers],
            instance_ids=[instance.id],
        ),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)

    assert any('"status": "deployed"' in event["data"] for event in events)
    assert [
        {"name": item["name"], "models": list(item["models"])}
        for item in written_configs[0]["custom_providers"]
    ] == expected_snapshot
    assert persist.await_args.kwargs["providers"] == expected_snapshot
    assert "secret" not in repr(persist.await_args.kwargs["providers"])
    deployment_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deploy_put_failure_does_not_replace_provider_snapshot(monkeypatch):
    provider_id, validation_session, snapshot_session = _deploy_fixture_sessions()

    class FailingDashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, _config):
            raise HermesError(500, "token=must-not-leak")

    sessions = iter([validation_session, snapshot_session])
    persist = AsyncMock()
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(
        provider_routes, "HermesService", lambda **_kwargs: FailingDashboard()
    )
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=SimpleNamespace(actual_state="running")),
    )
    monkeypatch.setattr(provider_routes, "persist_manager_resource_snapshot", persist)

    response = await deploy_providers(
        DeployRequest(provider_ids=[provider_id], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)

    payload = " ".join(event["data"] for event in events)
    assert '"status": "failed"' in payload
    assert "must-not-leak" not in payload
    persist.assert_not_awaited()
    snapshot_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_deploy_records_provider_snapshot_immediately_after_config_put(
    monkeypatch,
):
    provider_id, validation_session, snapshot_session = _deploy_fixture_sessions()

    class AuxiliaryFailureDashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, _config):
            return None

        async def get_auxiliary_models(self):
            raise HermesError(500, "auxiliary failed")

    sessions = iter([validation_session, snapshot_session])
    persist = AsyncMock()
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(
        provider_routes,
        "HermesService",
        lambda **_kwargs: AuxiliaryFailureDashboard(),
    )
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=SimpleNamespace(actual_state="running")),
    )
    monkeypatch.setattr(provider_routes, "persist_manager_resource_snapshot", persist)

    response = await deploy_providers(
        DeployRequest(provider_ids=[provider_id], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)

    assert any('"status": "failed"' in event["data"] for event in events)
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["providers"] == [
        {"name": "instance-provider", "models": ["model-1"]}
    ]
    snapshot_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deploy_allows_empty_provider_list_to_clear_instance(monkeypatch):
    _, validation_session, deployment_session = _deploy_fixture_sessions()
    validation_session.execute = AsyncMock(
        side_effect=[
            _Result([]),
            _Result(
                [
                    SimpleNamespace(
                        id="instance-1", name="Agent 1", actual_state="running"
                    )
                ]
            ),
        ]
    )
    written_configs = []

    class Dashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {"custom_providers": [{"name": "old", "models": {"old": {}}}]}

        async def put_config(self, config):
            written_configs.append(config)

        async def get_auxiliary_models(self):
            return {"tasks": []}

    sessions = iter([validation_session, deployment_session])
    persist = AsyncMock()
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(provider_routes, "HermesService", lambda **_kwargs: Dashboard())
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=SimpleNamespace(actual_state="running")),
    )
    monkeypatch.setattr(provider_routes, "persist_manager_resource_snapshot", persist)

    response = await deploy_providers(
        DeployRequest(provider_ids=[], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)

    assert any('"status": "deployed"' in event["data"] for event in events)
    assert written_configs[0]["custom_providers"] == []
    assert persist.await_args.kwargs["providers"] == []


@pytest.mark.asyncio
async def test_deploy_snapshot_error_does_not_expose_exception(monkeypatch):
    provider_id, validation_session, deployment_session = _deploy_fixture_sessions()

    class Dashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, _config):
            return None

    sessions = iter([validation_session, deployment_session])
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(provider_routes, "HermesService", lambda **_kwargs: Dashboard())
    monkeypatch.setattr(
        provider_routes,
        "lock_instance_for_snapshot",
        AsyncMock(return_value=SimpleNamespace(actual_state="running")),
    )
    monkeypatch.setattr(
        provider_routes,
        "persist_manager_resource_snapshot",
        AsyncMock(side_effect=RuntimeError("db-password=must-not-leak")),
    )

    response = await deploy_providers(
        DeployRequest(provider_ids=[provider_id], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    events = await _consume_deploy_events(response)
    payload = " ".join(event["data"] for event in events)
    errors = [json.loads(event["data"]).get("error") for event in events]

    assert "部署状态保存失败，请稍后重试" in errors
    assert "must-not-leak" not in payload


@pytest.mark.asyncio
async def test_concurrent_deploys_serialize_put_through_snapshot_commit(monkeypatch):
    instance = SimpleNamespace(id="instance-1", name="Agent 1", actual_state="running")

    def validation_session():
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[_Result([]), _Result([instance])])
        return session

    deploy_sessions = [MagicMock(), MagicMock()]
    order = []
    row_lock = asyncio.Lock()

    async def acquire_lock(session, **_kwargs):
        await row_lock.acquire()
        order.append("lock")
        return instance

    for session in deploy_sessions:

        async def commit():
            order.append("commit")
            row_lock.release()

        session.commit = AsyncMock(side_effect=commit)

    class Dashboard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get_config(self):
            return {}

        async def put_config(self, _config):
            order.append("put")
            await asyncio.sleep(0)

        async def get_auxiliary_models(self):
            return {"tasks": []}

    sessions = iter([validation_session(), validation_session(), *deploy_sessions])
    monkeypatch.setattr(
        provider_routes, "async_session_maker", lambda: _SessionContext(next(sessions))
    )
    monkeypatch.setattr(provider_routes, "HermesService", lambda **_kwargs: Dashboard())
    monkeypatch.setattr(provider_routes, "lock_instance_for_snapshot", acquire_lock)
    monkeypatch.setattr(
        provider_routes, "persist_manager_resource_snapshot", AsyncMock()
    )

    first = await deploy_providers(
        DeployRequest(provider_ids=[], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    second = await deploy_providers(
        DeployRequest(provider_ids=[], instance_ids=["instance-1"]),
        tenant_id="tenant-1",
    )
    await asyncio.gather(
        _consume_deploy_events(first),
        _consume_deploy_events(second),
    )

    assert order == ["lock", "put", "commit", "lock", "put", "commit"]

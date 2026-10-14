"""Database-isolated contract tests for safe workflow API projections."""

import json
from typing import Any, get_args
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy.exc import ProgrammingError

from app.api.routes.workflows import _agent_catalog_item, router
from app.db.session import get_session
from app.main import app
from app.models.instance import ServiceInstance
from app.models.workflow import WorkflowNodeTypeDefinition
from app.schemas.workflow import NodeType
from app.services.workflow.compiler import SUPPORTED_NODE_TYPES
from app.services.workflow.events import parse_last_event_id, public_event_data
from app.services.workflow.node_types import (
    NodeTypeCatalogIntegrityError,
    list_node_type_definitions,
    node_type_ids,
)


class _CatalogScalars:
    def __init__(self, rows: list[WorkflowNodeTypeDefinition]) -> None:
        self._rows = rows

    def all(self) -> list[WorkflowNodeTypeDefinition]:
        return self._rows


class _CatalogSession:
    def __init__(self, rows: list[WorkflowNodeTypeDefinition]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def scalars(self, statement: object) -> _CatalogScalars:
        self.statements.append(statement)
        return _CatalogScalars(self.rows)


class _UnavailableCatalogSession:
    async def scalars(self, statement: object) -> _CatalogScalars:
        del statement
        raise ProgrammingError("SELECT", {}, RuntimeError("relation does not exist"))


def _database_definition(node_type: str) -> dict[str, Any]:
    input_port = {
        "id": "default",
        "name": "默认输入",
        "description": "数据库目录中的默认输入。",
        "dynamic": False,
    }
    output_port: dict[str, Any] = {
        "id": "default",
        "name": "默认输出",
        "description": "数据库目录中的默认输出。",
        "dynamic": False,
    }
    definition: dict[str, Any] = {
        "type": node_type,
        "name": f"数据库-{node_type}",
        "description": "用于验证接口从数据库读取，而非静态内存。",
        "category": "agent" if node_type == "hermes_agent" else "control",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [] if node_type == "start" else [input_port],
        "output_ports": [] if node_type == "end" else [output_port],
        "config_schema": {"type": "object", "additionalProperties": True},
        "default_config": {},
        "capabilities": {
            "container": node_type == "loop",
            "nested_loop": False,
            "artifact_workspace": True,
            "variables": True,
            "control_decision": node_type in {"hermes_agent", "condition", "loop"},
        },
    }
    if node_type == "condition":
        definition["output_ports"] = [
            {
                "id": "branch",
                "name": "条件分支",
                "description": "由数据库定义的动态分支。",
                "dynamic": True,
                "source": "config.ports[]",
            }
        ]
    if node_type == "loop":
        definition["default_config"] = {
            "termination": {"mode": "formula"},
            "limits": {"max_iterations": 1},
        }
    return definition


def _database_catalog_rows() -> list[WorkflowNodeTypeDefinition]:
    return [
        WorkflowNodeTypeDefinition(
            type=node_type,
            display_order=index,
            definition=_database_definition(node_type),
        )
        for index, node_type in enumerate(
            ("start", "end", "hermes_agent", "condition", "loop")
        )
    ]


def test_agent_catalog_projection_is_secret_free_and_route_precedes_uuid_match():
    instance = ServiceInstance(
        id="agent-1",
        tenant_id="tenant-1",
        template_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="研究助手",
        actual_state="exited",
        config={
            "api_key": "runtime-secret",
            "manager_resource_snapshot": {
                "model": {
                    "provider": "openai",
                    "model": "gpt-5",
                    "api_key": "must-not-leak",
                },
                "knowledge_bases": [
                    {
                        "id": "kb-1",
                        "name": "产品知识库",
                        "base_url": "https://private.example",
                    }
                ],
                "mcps": [
                    {
                        "id": "mcp-1",
                        "name": "检索工具",
                        "enabled": True,
                        "headers": {"Authorization": "must-not-leak"},
                    }
                ],
                "skills": [
                    {"slug": "research", "name": "研究", "private": "must-not-leak"}
                ],
                "config_updated_at": "2026-07-22T08:00:00Z",
            },
        },
    )

    projection = _agent_catalog_item(instance)

    assert projection == {
        "instance_id": "agent-1",
        "name": "研究助手",
        "actual_state": "exited",
        "snapshot_state": "known",
        "model": {"provider": "openai", "model": "gpt-5"},
        "knowledge_bases": [{"id": "kb-1", "name": "产品知识库"}],
        "mcps": [{"id": "mcp-1", "name": "检索工具", "enabled": True}],
        "skills": [{"slug": "research", "name": "研究"}],
        "config_updated_at": "2026-07-22T08:00:00Z",
    }
    paths = [route.path for route in router.routes]
    assert paths.index("/workflows/agent-catalog") < paths.index(
        "/workflows/{workflow_id}"
    )


def test_run_event_projection_drops_internal_version_and_hermes_identifiers():
    started = public_event_data(
        "workflow.started",
        {
            "workflow_id": "workflow-1",
            "version_number": 12,
            "workflow_version_id": "must-not-leak",
        },
    )
    node_started = public_event_data(
        "node.started",
        {
            "node_run_id": "node-run-1",
            "node_id": "hermes_agent_0123456789abcdef",
            "external_run_id": "must-not-leak",
            "attempt_id": "must-not-leak",
            "execution_id": "must-not-leak",
        },
    )

    assert started == {"workflow_id": "workflow-1"}
    assert node_started == {
        "node_run_id": "node-run-1",
        "node_id": "hermes_agent_0123456789abcdef",
    }
    assert public_event_data("future.private.event", {"secret": "must-not-leak"}) == {}


def test_sse_last_event_id_parser_rejects_non_integer_or_overflow_input():
    assert parse_last_event_id("42") == 42
    assert parse_last_event_id("2147483647") == 2147483647
    assert parse_last_event_id("2147483648") is None
    assert parse_last_event_id("9" * 4301) is None
    assert parse_last_event_id("not-a-sequence") is None


def test_workflow_router_does_not_accept_public_hermes_run_binding():
    paths = {route.path for route in router.routes}

    assert "/workflows/node-runs/{node_run_id}/bind-external-run" not in paths


@pytest.mark.asyncio
async def test_node_type_catalog_reads_database_rows_and_preserves_metadata():
    session = _CatalogSession(_database_catalog_rows())
    items = await list_node_type_definitions(session)  # type: ignore[arg-type]

    assert [item["type"] for item in items] == [
        "start",
        "end",
        "hermes_agent",
        "condition",
        "loop",
    ]
    assert items[0]["name"] == "数据库-start"
    assert node_type_ids() == SUPPORTED_NODE_TYPES == set(get_args(NodeType))
    required = {
        "type",
        "name",
        "description",
        "category",
        "type_version",
        "executor_version",
        "input_ports",
        "output_ports",
        "config_schema",
        "default_config",
        "capabilities",
    }
    assert all(required <= set(item) for item in items)
    for item in items:
        assert item["config_schema"]["additionalProperties"] is True
        Draft202012Validator.check_schema(item["config_schema"])

    condition = next(item for item in items if item["type"] == "condition")
    assert condition["output_ports"] == [
        {
            "id": "branch",
            "name": "条件分支",
            "description": "由数据库定义的动态分支。",
            "dynamic": True,
            "source": "config.ports[]",
        }
    ]
    loop = next(item for item in items if item["type"] == "loop")
    assert loop["capabilities"]["container"] is True
    assert loop["capabilities"]["nested_loop"] is False

    items[0]["name"] = "mutated"
    fresh_items = await list_node_type_definitions(session)  # type: ignore[arg-type]
    assert fresh_items[0]["name"] == "数据库-start"
    assert "ORDER BY" in str(session.statements[0])
    assert "display_order" in str(session.statements[0])

    serialized = json.dumps(items, ensure_ascii=False)
    assert all(
        value not in serialized
        for value in ("api_key", "execution_id", "bridge_token", "external_run_id")
    )

    paths = [route.path for route in router.routes]
    assert paths.index("/workflows/node-types") < paths.index(
        "/workflows/{workflow_id}"
    )


@pytest.mark.asyncio
async def test_node_type_catalog_rejects_incomplete_or_corrupt_database_rows():
    incomplete = _CatalogSession(_database_catalog_rows()[:-1])
    with pytest.raises(NodeTypeCatalogIntegrityError):
        await list_node_type_definitions(incomplete)  # type: ignore[arg-type]

    mismatched_rows = _database_catalog_rows()
    mismatched_rows[0].definition["type"] = "end"
    mismatched = _CatalogSession(mismatched_rows)
    with pytest.raises(NodeTypeCatalogIntegrityError):
        await list_node_type_definitions(mismatched)  # type: ignore[arg-type]

    unknown_rows = _database_catalog_rows()
    unknown_rows[-1].type = "unknown"
    unknown_rows[-1].definition["type"] = "unknown"
    unknown = _CatalogSession(unknown_rows)
    with pytest.raises(NodeTypeCatalogIntegrityError):
        await list_node_type_definitions(unknown)  # type: ignore[arg-type]

    truncated_rows = _database_catalog_rows()
    truncated_rows[0].definition = {"type": "start"}
    truncated = _CatalogSession(truncated_rows)
    with pytest.raises(NodeTypeCatalogIntegrityError):
        await list_node_type_definitions(truncated)  # type: ignore[arg-type]

    invalid_schema_rows = _database_catalog_rows()
    invalid_schema_rows[0].definition["config_schema"] = {"type": 1}
    invalid_schema = _CatalogSession(invalid_schema_rows)
    with pytest.raises(NodeTypeCatalogIntegrityError):
        await list_node_type_definitions(invalid_schema)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_node_type_catalog_endpoint_reads_database_and_keeps_tenant_header(
    client,
):
    catalog_session = _CatalogSession(_database_catalog_rows())

    async def override_session():
        yield catalog_session

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_session
    try:
        response = await client.get(
            "/v1/workflows/node-types", headers={"X-Tenant-ID": "tenant-1"}
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 5
    assert body["data"]["items"][0]["name"] == "数据库-start"


@pytest.mark.asyncio
async def test_node_type_catalog_endpoint_rejects_incomplete_database_catalog(client):
    catalog_session = _CatalogSession(_database_catalog_rows()[:-1])

    async def override_session():
        yield catalog_session

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_session
    try:
        response = await client.get("/v1/workflows/node-types")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous

    assert response.status_code == 503
    assert response.json()["detail"] == "工作流节点类型目录未初始化或不完整"


@pytest.mark.asyncio
async def test_node_type_catalog_endpoint_rejects_unmigrated_database_table(client):
    async def override_session():
        yield _UnavailableCatalogSession()

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_session
    try:
        response = await client.get("/v1/workflows/node-types")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous

    assert response.status_code == 503
    assert response.json()["detail"] == "工作流节点类型目录未初始化或不完整"

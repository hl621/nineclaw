"""PostgreSQL runtime tests for the durable Hermes workflow state machine.

Set ``WORKFLOW_TEST_DATABASE_URL`` to a disposable PostgreSQL database that
has been migrated to revision 025.  The suite wraps each test in an outer
transaction and rolls it back, so it never leaves workflow data behind.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import workflows as workflow_routes
from app.api.routes import workflow_workspace as workspace_routes
from app.core.config import settings
from app.models.instance import ServiceInstance
from app.models.template import ServiceTemplate
from app.models.tenant import Tenant
from app.models.workflow import (
    Workflow,
    WorkflowArtifact,
    WorkflowControlDecision,
    WorkflowEdgeRun,
    WorkflowEvent,
    WorkflowJob,
    WorkflowNodeAttempt,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowScopeRun,
    WorkflowVariableWrite,
    WorkflowVersion,
    utcnow,
)
from app.services.workflow.artifacts import ArtifactStoreError, LocalArtifactStore
from app.services.workflow.compiler import compile_workflow
from app.services.workflow.engine import (
    HermesMonitor,
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowVariableConflictError,
)
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow import scheduler as scheduler_module
from app.services.workflow.workspace_auth import workspace_token_for_execution
from app.services.workflow.state import EDGE_TAKEN


WORKFLOW_TEST_DATABASE_URL = os.getenv("WORKFLOW_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not WORKFLOW_TEST_DATABASE_URL,
    reason="需要 WORKFLOW_TEST_DATABASE_URL 指向已迁移的 PostgreSQL",
)


@pytest.fixture(autouse=True)
def _workspace_bridge_secret(monkeypatch):
    monkeypatch.setattr(settings, "workflow_workspace_bridge_secret", "test-secret")


START_NODE_ID = "start_0000000000004001"
AGENT_NODE_ID = "hermes_agent_0000000000004002"
END_NODE_ID = "end_0000000000004003"
LOOP_NODE_ID = "loop_0000000000004004"
LOOP_BODY_START_NODE_ID = "start_0000000000004005"
LOOP_BODY_END_NODE_ID = "end_0000000000004006"
LOOP_BODY_AGENT_NODE_ID = "hermes_agent_0000000000004007"
PARALLEL_AGENT_ID = "hermes_agent_0000000000004008"
PARALLEL_PASSTHROUGH_ID = "hermes_agent_0000000000004009"
CONDITION_NODE_ID = "condition_0000000000004010"
APPROVED_END_NODE_ID = "end_0000000000004011"
REJECTED_END_NODE_ID = "end_0000000000004012"


@pytest_asyncio.fixture
async def workflow_sessions():
    engine: AsyncEngine = create_async_engine(WORKFLOW_TEST_DATABASE_URL)
    connection: AsyncConnection = await engine.connect()
    outer_transaction = await connection.begin()
    sessions = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield sessions
    finally:
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


def _linear_definition(
    *,
    instance_id: str | None = None,
    artifact_limit: int = 1024,
) -> dict:
    nodes = [{"id": START_NODE_ID, "type": "start"}]
    edges = []
    if instance_id is not None:
        nodes.append(
            {
                "id": AGENT_NODE_ID,
                "type": "hermes_agent",
                "config": {"instance_id": instance_id, "prompt": "处理输入"},
            }
        )
        edges.extend(
            [
                {
                    "id": "start-agent",
                    "source_node_id": START_NODE_ID,
                    "target_node_id": AGENT_NODE_ID,
                },
                {
                    "id": "agent-end",
                    "source_node_id": AGENT_NODE_ID,
                    "target_node_id": END_NODE_ID,
                },
            ]
        )
    else:
        edges.append(
            {
                "id": "start-end",
                "source_node_id": START_NODE_ID,
                "target_node_id": END_NODE_ID,
            }
        )
    nodes.append({"id": END_NODE_ID, "type": "end"})
    return {
        "schema_version": 2,
        "nodes": nodes,
        "edges": edges,
        "limits": {"max_artifact_bytes": artifact_limit, "max_hermes_runs": 3},
    }


def _loop_definition() -> dict:
    body = {
        "schema_version": 2,
        "nodes": [
            {"id": LOOP_BODY_START_NODE_ID, "type": "start"},
            {"id": LOOP_BODY_END_NODE_ID, "type": "end"},
        ],
        "edges": [
            {
                "id": "body-start-end",
                "source_node_id": LOOP_BODY_START_NODE_ID,
                "target_node_id": LOOP_BODY_END_NODE_ID,
            }
        ],
    }
    return {
        "schema_version": 2,
        "nodes": [
            {"id": START_NODE_ID, "type": "start"},
            {
                "id": LOOP_NODE_ID,
                "type": "loop",
                "config": {
                    "body": body,
                    "termination": {"mode": "formula", "expression": False},
                    "limits": {"max_iterations": 2},
                },
            },
            {"id": END_NODE_ID, "type": "end"},
        ],
        "edges": [
            {
                "id": "start-loop",
                "source_node_id": START_NODE_ID,
                "target_node_id": LOOP_NODE_ID,
            },
            {
                "id": "loop-end",
                "source_node_id": LOOP_NODE_ID,
                "target_node_id": END_NODE_ID,
            },
        ],
    }


def _loop_artifact_definition(instance_id: str) -> dict:
    definition = _loop_definition()
    loop = definition["nodes"][1]
    body = loop["config"]["body"]
    body["nodes"].insert(
        1,
        {
            "id": LOOP_BODY_AGENT_NODE_ID,
            "type": "hermes_agent",
            "config": {"instance_id": instance_id, "prompt": "生成迭代产物"},
        },
    )
    body["edges"] = [
        {
            "id": "body-start-agent",
            "source_node_id": LOOP_BODY_START_NODE_ID,
            "target_node_id": LOOP_BODY_AGENT_NODE_ID,
        },
        {
            "id": "body-agent-end",
            "source_node_id": LOOP_BODY_AGENT_NODE_ID,
            "target_node_id": LOOP_BODY_END_NODE_ID,
        },
    ]
    loop["config"]["termination"] = {
        "mode": "formula",
        # Formula ``true`` is a terminal decision, so iteration 1 stops the
        # Loop after two completed Body scopes.
        "expression": {"gte": [{"path": "system.iteration_index"}, 1]},
    }
    return definition


def _parallel_variable_definition() -> dict:
    return {
        "schema_version": 2,
        "variables": {"summary": {"type": "string"}},
        "nodes": [
            {"id": START_NODE_ID, "type": "start"},
            {
                "id": AGENT_NODE_ID,
                "type": "hermes_agent",
                "config": {"instance_id": "agent-a", "prompt": "写入初值"},
            },
            {
                "id": PARALLEL_AGENT_ID,
                "type": "hermes_agent",
                "config": {"instance_id": "agent-b", "prompt": "覆盖变量"},
            },
            {
                "id": PARALLEL_PASSTHROUGH_ID,
                "type": "hermes_agent",
                "config": {"instance_id": "agent-c", "prompt": "透传变量"},
            },
            {"id": END_NODE_ID, "type": "end"},
        ],
        "edges": [
            {
                "id": "start-a",
                "source_node_id": START_NODE_ID,
                "target_node_id": AGENT_NODE_ID,
            },
            {
                "id": "a-b",
                "source_node_id": AGENT_NODE_ID,
                "target_node_id": PARALLEL_AGENT_ID,
            },
            {
                "id": "a-c",
                "source_node_id": AGENT_NODE_ID,
                "target_node_id": PARALLEL_PASSTHROUGH_ID,
            },
            {
                "id": "b-end",
                "source_node_id": PARALLEL_AGENT_ID,
                "target_node_id": END_NODE_ID,
            },
            {
                "id": "c-end",
                "source_node_id": PARALLEL_PASSTHROUGH_ID,
                "target_node_id": END_NODE_ID,
            },
        ],
    }


def _loop_variable_definition(instance_id: str) -> dict:
    definition = _loop_artifact_definition(instance_id)
    definition["variables"] = {"summary": {"type": "string"}}
    return definition


def _formula_condition_definition() -> dict:
    return {
        "schema_version": 2,
        "nodes": [
            {"id": START_NODE_ID, "type": "start"},
            {
                "id": CONDITION_NODE_ID,
                "type": "condition",
                "config": {
                    "mode": "formula",
                    "ports": ["approved", "rejected"],
                    "expression": {"eq": [1, 1]},
                    "true_port": "approved",
                    "false_port": "rejected",
                },
            },
            {"id": APPROVED_END_NODE_ID, "type": "end"},
            {"id": REJECTED_END_NODE_ID, "type": "end"},
        ],
        "edges": [
            {
                "id": "start-condition",
                "source_node_id": START_NODE_ID,
                "target_node_id": CONDITION_NODE_ID,
            },
            {
                "id": "condition-approved",
                "source_node_id": CONDITION_NODE_ID,
                "source_port": "approved",
                "target_node_id": APPROVED_END_NODE_ID,
            },
            {
                "id": "condition-rejected",
                "source_node_id": CONDITION_NODE_ID,
                "source_port": "rejected",
                "target_node_id": REJECTED_END_NODE_ID,
            },
        ],
    }


def _agent_condition_definition(instance_id: str) -> dict:
    definition = _formula_condition_definition()
    definition["nodes"].insert(
        1,
        {
            "id": AGENT_NODE_ID,
            "type": "hermes_agent",
            "config": {"instance_id": instance_id, "prompt": "提交条件端口"},
        },
    )
    condition = definition["nodes"][2]
    condition["config"] = {
        "mode": "agent",
        "ports": ["approved", "rejected"],
    }
    definition["edges"][0] = {
        "id": "start-agent",
        "source_node_id": START_NODE_ID,
        "target_node_id": AGENT_NODE_ID,
    }
    definition["edges"].insert(
        1,
        {
            "id": "agent-condition",
            "source_node_id": AGENT_NODE_ID,
            "target_node_id": CONDITION_NODE_ID,
        },
    )
    return definition


def _agent_loop_definition(instance_id: str) -> dict:
    definition = _loop_variable_definition(instance_id)
    definition["nodes"][1]["config"]["termination"] = {
        "mode": "agent",
        "source_node_id": LOOP_BODY_AGENT_NODE_ID,
    }
    return definition


def _definition_nodes(definition: dict):
    for node in definition.get("nodes", []):
        yield node
        if node.get("type") == "loop":
            body = node.get("config", {}).get("body")
            if isinstance(body, dict):
                yield from _definition_nodes(body)


async def _create_run(
    sessions: async_sessionmaker[AsyncSession],
    definition: dict,
    *,
    with_instance: bool = False,
) -> tuple[str, UUID, str | None]:
    tenant_id = f"workflow-test-{uuid4().hex[:20]}"
    instance_id = next(
        (
            node.get("config", {}).get("instance_id")
            for node in _definition_nodes(definition)
            if node.get("type") == "hermes_agent"
        ),
        None,
    )
    if with_instance:
        assert isinstance(instance_id, str) and instance_id
    compiled = compile_workflow(definition)
    async with sessions() as session:
        session.add(Tenant(id=tenant_id, name="workflow test", api_key_hash="test"))
        if instance_id is not None:
            template = ServiceTemplate(name="workflow", image="test:latest")
            session.add(template)
            await session.flush()
            session.add(
                ServiceInstance(
                    id=instance_id,
                    tenant_id=tenant_id,
                    template_id=template.id,
                    name=instance_id,
                    desired_state="running",
                    actual_state="running",
                )
            )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=f"workflow-{uuid4().hex}",
            draft_definition=compiled.definition,
        )
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=1,
            definition=compiled.definition,
            compiled_plan=compiled.plan,
            checksum=compiled.checksum,
        )
        session.add(version)
        await session.flush()
        run = await WorkflowEngine(session).create_run(
            tenant_id=tenant_id,
            workflow=workflow,
            version=version,
            workflow_input={"topic": "test"},
        )
        await session.commit()
        return tenant_id, run.id, instance_id


async def _create_legacy_v1_run(
    sessions: async_sessionmaker[AsyncSession], *, with_external_attempt: bool
) -> tuple[str, UUID]:
    """Persist a pre-cutover Run without entering the v2 creation API."""
    tenant_id = f"workflow-v1-test-{uuid4().hex[:20]}"
    legacy_definition = {"schema_version": 1}
    async with sessions() as session:
        session.add(
            Tenant(id=tenant_id, name="legacy workflow test", api_key_hash="test")
        )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=f"legacy-workflow-{uuid4().hex}",
            draft_definition=legacy_definition,
        )
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=1,
            definition=legacy_definition,
            compiled_plan={},
            checksum="0" * 64,
        )
        session.add(version)
        await session.flush()
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            status="running",
            budget={},
        )
        session.add(run)
        await session.flush()
        scope = WorkflowScopeRun(
            tenant_id=tenant_id,
            workflow_run_id=run.id,
            kind="root",
            state={"plan": {}},
        )
        session.add(scope)
        await session.flush()
        node = WorkflowNodeRun(
            tenant_id=tenant_id,
            workflow_run_id=run.id,
            scope_run_id=scope.id,
            node_definition_id=AGENT_NODE_ID,
            node_type="hermes_agent",
            status="running" if with_external_attempt else "ready",
            input_snapshot={"artifact_ids": []},
        )
        session.add(node)
        await session.flush()
        attempt: WorkflowNodeAttempt | None = None
        if with_external_attempt:
            attempt = WorkflowNodeAttempt(
                tenant_id=tenant_id,
                workflow_run_id=run.id,
                node_run_id=node.id,
                generation=1,
                execution_id=f"legacy-{uuid4().hex}",
                executor_instance_id="legacy-instance",
                external_run_id="legacy-hermes-run",
                status="dispatched",
            )
            session.add(attempt)
            await session.flush()
            node.active_attempt_id = attempt.id
        session.add(
            WorkflowJob(
                tenant_id=tenant_id,
                workflow_run_id=run.id,
                scope_run_id=scope.id,
                node_run_id=node.id,
                attempt_id=attempt.id if attempt is not None else None,
                job_type="monitor_hermes" if attempt is not None else "dispatch_node",
                dedupe_key=f"legacy-job-{run.id}",
                payload={},
            )
        )
        await session.commit()
        return tenant_id, run.id


async def _node(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, definition_id: str
) -> WorkflowNodeRun:
    async with sessions() as session:
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == definition_id,
            )
        )
        assert node is not None
        return node


@pytest.mark.asyncio
async def test_loop_cancellation_propagates_from_body_to_parent_and_root(
    workflow_sessions,
):
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _loop_definition())
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start -> loop ready
    assert await scheduler.run_once()  # loop -> body start ready

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        await WorkflowEngine(session).request_cancel(run=run, requested_by=tenant_id)
        await session.commit()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        loop = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == LOOP_NODE_ID,
            )
        )
        assert run is not None and loop is not None
        assert run.status == "cancelled"
        assert run.output == {"final_artifact_ids": []}
        assert loop.status == "cancelled"


@pytest.mark.asyncio
async def test_formula_condition_selects_only_its_true_port(workflow_sessions):
    _, run_id, _ = await _create_run(workflow_sessions, _formula_condition_definition())
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # condition
    assert await scheduler.run_once()  # approved end

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        nodes = {
            item.node_definition_id: item.status
            for item in (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run_id
                    )
                )
            ).all()
        }
        assert run is not None and run.status == "succeeded"
        assert nodes[CONDITION_NODE_ID] == "succeeded"
        assert nodes[APPROVED_END_NODE_ID] == "succeeded"
        assert nodes[REJECTED_END_NODE_ID] == "skipped"


@pytest.mark.asyncio
async def test_agent_condition_accepts_one_submitted_port(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _agent_condition_definition(instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # Agent dispatch, create control token
    async with workflow_sessions() as session:
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id,
                WorkflowNodeAttempt.status == "dispatched",
            )
        )
        decision = await session.scalar(
            select(WorkflowControlDecision).where(
                WorkflowControlDecision.attempt_id == attempt.id  # type: ignore[union-attr]
            )
        )
        assert attempt is not None and decision is not None
        response = await workspace_routes.submit_condition_selection(
            body={
                "execution_id": attempt.execution_id,
                "token": decision.token,
                "port": "approved",
            },
            session=session,
            instance_id=instance_id,
            workspace_token=workspace_token_for_execution(
                execution_id=attempt.execution_id,
                instance_id=instance_id,
            ),
        )
        assert response == {"data": {"accepted": True}}

    assert await scheduler.run_once()  # Agent monitor -> condition ready
    assert await scheduler.run_once()  # condition -> approved end ready
    assert await scheduler.run_once()  # approved end
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        nodes = {
            item.node_definition_id: item.status
            for item in (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run_id
                    )
                )
            ).all()
        }
        assert run is not None and run.status == "succeeded"
        assert nodes[APPROVED_END_NODE_ID] == "succeeded"
        assert nodes[REJECTED_END_NODE_ID] == "skipped"


@pytest.mark.asyncio
async def test_agent_loop_uses_explicit_continue_then_stop_decisions(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _agent_loop_definition(instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    decisions: list[bool] = []

    for _ in range(20):
        async with workflow_sessions() as session:
            pending = list(
                (
                    await session.scalars(
                        select(WorkflowControlDecision)
                        .where(
                            WorkflowControlDecision.workflow_run_id == run_id,
                            WorkflowControlDecision.kind == "loop",
                            WorkflowControlDecision.status == "pending",
                        )
                        .order_by(WorkflowControlDecision.created_at)
                    )
                ).all()
            )
            for decision in pending:
                attempt = await session.get(WorkflowNodeAttempt, decision.attempt_id)
                assert attempt is not None
                should_continue = not decisions
                response = await workspace_routes.submit_loop_decision(
                    body={
                        "execution_id": attempt.execution_id,
                        "token": decision.token,
                        "should_continue": should_continue,
                    },
                    session=session,
                    instance_id=instance_id,
                    workspace_token=workspace_token_for_execution(
                        execution_id=attempt.execution_id,
                        instance_id=instance_id,
                    ),
                )
                assert response == {"data": {"accepted": True}}
                decisions.append(should_continue)

        assert await scheduler.run_once()
        async with workflow_sessions() as session:
            run = await session.get(WorkflowRun, run_id)
            assert run is not None
            if run.status in {"succeeded", "failed", "cancelled"}:
                break
    else:
        raise AssertionError("Agent Loop 未在预期 Job 数内终态")

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        loop = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == LOOP_NODE_ID,
            )
        )
        assert run is not None and loop is not None
        assert run.status == "succeeded"
        assert decisions == [True, False]
        assert loop.output is not None and loop.output["iteration_count"] == 2


@pytest.mark.asyncio
async def test_parallel_passthrough_of_old_variable_conflicts_with_new_value(
    workflow_sessions,
):
    _, run_id, _ = await _create_run(workflow_sessions, _parallel_variable_definition())
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        scope = await session.scalar(
            select(WorkflowScopeRun).where(WorkflowScopeRun.workflow_run_id == run_id)
        )
        nodes = {
            item.node_definition_id: item
            for item in (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run_id
                    )
                )
            ).all()
        }
        edges = {
            item.edge_definition_id: item
            for item in (
                await session.scalars(
                    select(WorkflowEdgeRun).where(
                        WorkflowEdgeRun.workflow_run_id == run_id
                    )
                )
            ).all()
        }
        assert run is not None and scope is not None
        for edge_id in ("a-b", "a-c", "b-end", "c-end"):
            edges[edge_id].status = EDGE_TAKEN
        nodes[PARALLEL_AGENT_ID].status = "succeeded"
        nodes[PARALLEL_PASSTHROUGH_ID].status = "succeeded"
        nodes[PARALLEL_AGENT_ID].variable_state = {
            "summary": {
                "value": "new",
                "origin_scope_run_id": str(scope.id),
                "origin_node_definition_id": PARALLEL_AGENT_ID,
            }
        }
        nodes[PARALLEL_PASSTHROUGH_ID].variable_state = {
            "summary": {
                "value": "old",
                "origin_scope_run_id": str(scope.id),
                "origin_node_definition_id": AGENT_NODE_ID,
            }
        }
        await session.flush()

        with pytest.raises(WorkflowVariableConflictError, match="summary"):
            await WorkflowEngine(session)._resolve_variable_state(
                run=run,
                scope=scope,
                node=nodes[END_NODE_ID],
            )


@pytest.mark.asyncio
async def test_loop_iteration_commits_and_overwrites_variable_for_next_iteration(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _loop_variable_definition(instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    writes: dict[UUID, str] = {}

    for _ in range(20):
        async with workflow_sessions() as session:
            attempts = list(
                (
                    await session.scalars(
                        select(WorkflowNodeAttempt)
                        .join(WorkflowNodeRun)
                        .where(
                            WorkflowNodeAttempt.workflow_run_id == run_id,
                            WorkflowNodeAttempt.status == "dispatched",
                            WorkflowNodeRun.node_definition_id
                            == LOOP_BODY_AGENT_NODE_ID,
                        )
                        .order_by(WorkflowNodeAttempt.generation)
                    )
                ).all()
            )
            for attempt in attempts:
                if attempt.id in writes:
                    continue
                value = f"iteration-{len(writes) + 1}"
                response = await workspace_routes.set_workspace_variable(
                    variable_name="summary",
                    body={"value": value},
                    execution_id=attempt.execution_id,
                    session=session,
                    instance_id=instance_id,
                    workspace_token=workspace_token_for_execution(
                        execution_id=attempt.execution_id,
                        instance_id=instance_id,
                    ),
                )
                assert response["data"]["value"] == value
                writes[attempt.id] = value

        assert await scheduler.run_once()
        async with workflow_sessions() as session:
            run = await session.get(WorkflowRun, run_id)
            assert run is not None
            if run.status in {"succeeded", "failed", "cancelled"}:
                break
    else:
        raise AssertionError("Loop Run 未在预期 Job 数内终态")

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        loop = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == LOOP_NODE_ID,
            )
        )
        assert run is not None and loop is not None
        assert run.status == "succeeded"
        assert list(writes.values()) == ["iteration-1", "iteration-2"]
        assert loop.variable_state["summary"]["value"] == "iteration-2"


@pytest.mark.asyncio
async def test_stale_monitor_result_cannot_override_manual_retry(workflow_sessions):
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    async with workflow_sessions() as session:
        scope = await session.scalar(
            select(WorkflowScopeRun).where(WorkflowScopeRun.workflow_run_id == run_id)
        )
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == START_NODE_ID,
            )
        )
        assert scope is not None and node is not None
        old_attempt = WorkflowNodeAttempt(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            node_run_id=node.id,
            generation=1,
            execution_id="old-attempt",
            status="abandoned",
            external_run_id="hermes-old",
        )
        session.add(old_attempt)
        await session.flush()
        node.active_attempt_id = uuid4()
        node.status = "ready"
        job = WorkflowJob(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            scope_run_id=scope.id,
            node_run_id=node.id,
            attempt_id=old_attempt.id,
            job_type="monitor_hermes",
            status="running",
            fencing_token=1,
            dedupe_key=f"stale-monitor-{uuid4().hex}",
        )
        session.add(job)
        await session.commit()

    monitor = HermesMonitor(
        job_id=job.id,
        fencing_token=1,
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        node_run_id=node.id,
        attempt_id=old_attempt.id,
        base_url="http://unused",
        api_key="",
        external_run_id="hermes-old",
    )
    async with workflow_sessions() as session:
        await WorkflowEngine(session).persist_monitor_result(
            monitor=monitor, payload={"status": "succeeded", "output": {"x": 1}}
        )
        await session.commit()

    async with workflow_sessions() as session:
        refreshed = await session.get(WorkflowNodeRun, node.id)
        assert refreshed is not None
        assert refreshed.status == "ready"
        assert refreshed.output is None


class _FakeGateway:
    create_payload: object = {"run_id": "hermes-1"}
    auto_increment_run_ids = True
    monitor_payload: object = {"status": "succeeded", "output": {"answer": "ok"}}
    stop_error: Exception | None = None
    create_calls = 0
    create_call_args: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monitor_calls: list[str] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def create_run(self, *_args, **_kwargs):
        type(self).create_calls += 1
        type(self).create_call_args.append((_args, _kwargs))
        if isinstance(type(self).create_payload, Exception):
            raise type(self).create_payload
        if type(self).auto_increment_run_ids and isinstance(
            type(self).create_payload, dict
        ):
            return {
                **type(self).create_payload,
                "run_id": f"hermes-{type(self).create_calls}",
            }
        return type(self).create_payload

    async def get_run(self, run_id: str):
        type(self).monitor_calls.append(run_id)
        if isinstance(type(self).monitor_payload, Exception):
            raise type(self).monitor_payload
        return type(self).monitor_payload

    async def stop_run(self, _run_id: str):
        if type(self).stop_error is not None:
            raise type(self).stop_error
        return {"accepted": True}


def _reset_gateway(
    *, create_payload=None, monitor_payload=None, stop_error=None
) -> None:
    _FakeGateway.create_payload = (
        {"run_id": "hermes-1"} if create_payload is None else create_payload
    )
    _FakeGateway.auto_increment_run_ids = create_payload is None
    _FakeGateway.monitor_payload = (
        {"status": "succeeded", "output": {"answer": "ok"}}
        if monitor_payload is None
        else monitor_payload
    )
    _FakeGateway.stop_error = stop_error
    _FakeGateway.create_calls = 0
    _FakeGateway.create_call_args = []
    _FakeGateway.monitor_calls = []


@pytest.mark.asyncio
async def test_hermes_dispatch_monitor_and_terminal_success(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    for _ in range(4):
        assert await scheduler.run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and agent is not None
        assert run.status == "succeeded"
        assert agent.status == "succeeded"
        assert agent.output is not None
        assert agent.output["node_output"]["name"] == "node-output.json"
        assert agent.output["node_output"]["kind"] == "system_output"
        assert _FakeGateway.create_calls == 1
        assert _FakeGateway.monitor_calls == ["hermes-1"]


@pytest.mark.asyncio
async def test_successful_business_run_collects_end_final_artifact_ids(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # Hermes dispatch
    artifact_id = uuid4()
    async with workflow_sessions() as session:
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert attempt is not None and agent is not None
        session.add(
            WorkflowArtifact(
                id=artifact_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                node_run_id=agent.id,
                created_by_attempt_id=attempt.id,
                name="final.txt",
                uri="s3://internal-workspace/final.txt",
                mime_type="text/plain",
                size_bytes=5,
                sha256="a" * 64,
                status="available",
            )
        )
        await session.commit()

    assert await scheduler.run_once()  # Hermes success -> end ready
    assert await scheduler.run_once()  # end -> final artifact collection

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None and run.output is not None
        assert run.status == "succeeded"
        assert run.output["final_artifact_ids"] == [str(artifact_id)]
        assert run.output["end_outputs"][0] == {"artifact_count": 3}
        assert "s3://internal-workspace/final.txt" not in json.dumps(run.output)


@pytest.mark.asyncio
async def test_loop_aggregates_active_attempt_artifacts_for_root_final_output(
    workflow_sessions, monkeypatch
):
    class _LoopGateway(_FakeGateway):
        next_run_id = 0

        async def create_run(self, *_args, **_kwargs):
            type(self).next_run_id += 1
            return {"run_id": f"hermes-loop-{type(self).next_run_id}"}

    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _LoopGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _loop_artifact_definition(instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    artifact_ids: list[UUID] = []
    artifact_attempt_ids: set[UUID] = set()
    stale_artifact_id: UUID | None = None

    for _ in range(20):
        async with workflow_sessions() as session:
            attempts = list(
                (
                    await session.scalars(
                        select(WorkflowNodeAttempt)
                        .join(WorkflowNodeRun)
                        .where(
                            WorkflowNodeAttempt.workflow_run_id == run_id,
                            WorkflowNodeAttempt.status == "dispatched",
                            WorkflowNodeRun.node_definition_id
                            == LOOP_BODY_AGENT_NODE_ID,
                        )
                        .order_by(WorkflowNodeAttempt.created_at)
                    )
                ).all()
            )
            for attempt in attempts:
                if attempt.id in artifact_attempt_ids:
                    continue
                artifact_id = uuid4()
                artifact_attempt_ids.add(attempt.id)
                artifact_ids.append(artifact_id)
                if stale_artifact_id is None:
                    stale_attempt_id = uuid4()
                    stale_artifact_id = uuid4()
                    session.add(
                        WorkflowNodeAttempt(
                            id=stale_attempt_id,
                            tenant_id=tenant_id,
                            workflow_run_id=run_id,
                            node_run_id=attempt.node_run_id,
                            generation=99,
                            execution_id=f"stale-{uuid4().hex}",
                            status="succeeded",
                        )
                    )
                    await session.flush()
                    session.add(
                        WorkflowArtifact(
                            id=stale_artifact_id,
                            tenant_id=tenant_id,
                            workflow_run_id=run_id,
                            node_run_id=attempt.node_run_id,
                            created_by_attempt_id=stale_attempt_id,
                            name="stale.txt",
                            uri=f"s3://internal-workspace/{stale_artifact_id}",
                            mime_type="text/plain",
                            size_bytes=10,
                            sha256="f" * 64,
                            status="available",
                        )
                    )
                session.add(
                    WorkflowArtifact(
                        id=artifact_id,
                        tenant_id=tenant_id,
                        workflow_run_id=run_id,
                        node_run_id=attempt.node_run_id,
                        created_by_attempt_id=attempt.id,
                        name=f"iteration-{len(artifact_ids)}.txt",
                        uri=f"s3://internal-workspace/{artifact_id}",
                        mime_type="text/plain",
                        size_bytes=10,
                        sha256=(str(len(artifact_ids)) * 64)[:64],
                        status="available",
                    )
                )
            await session.commit()

        assert await scheduler.run_once()
        async with workflow_sessions() as session:
            run = await session.get(WorkflowRun, run_id)
            assert run is not None
            if run.status in {"succeeded", "failed", "cancelled"}:
                break
    else:
        raise AssertionError("Loop Run 未在预期 Job 数内终态")

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        loop = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == LOOP_NODE_ID,
            )
        )
        assert run is not None and loop is not None
        assert run.status == "succeeded"
        assert len(artifact_ids) == 2
        assert stale_artifact_id is not None
        assert loop.output is not None
        assert loop.output["iteration_count"] == 2
        assert loop.output["artifact_count"] >= len(artifact_ids)
        assert run.output is not None
        assert run.output["final_artifact_ids"] == [
            str(artifact_id) for artifact_id in artifact_ids
        ]
        assert "s3://internal-workspace/" not in json.dumps(run.output)


@pytest.mark.asyncio
async def test_final_artifact_collection_ignores_foreign_run_artifact(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    artifact_id = uuid4()
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # Hermes dispatch
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and attempt is not None and agent is not None
        foreign_run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=run.workflow_id,
            workflow_version_id=run.workflow_version_id,
            status="succeeded",
            input={},
            budget={},
        )
        session.add(foreign_run)
        await session.flush()
        session.add(
            WorkflowArtifact(
                id=artifact_id,
                tenant_id=tenant_id,
                workflow_run_id=foreign_run.id,
                node_run_id=agent.id,
                created_by_attempt_id=attempt.id,
                name="foreign.txt",
                uri="s3://internal-workspace/foreign.txt",
                mime_type="text/plain",
                size_bytes=7,
                sha256="b" * 64,
                status="available",
            )
        )
        await session.commit()

    assert await scheduler.run_once()  # Hermes success -> end ready
    assert await scheduler.run_once()  # end -> final Artifact collection

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        scope = await session.scalar(
            select(WorkflowScopeRun).where(WorkflowScopeRun.workflow_run_id == run_id)
        )
        assert run is not None and scope is not None
        assert run.status == "succeeded"
        assert scope.status == "succeeded"
        assert run.output is not None
        assert run.output["final_artifact_ids"] == []
        assert run.output["end_outputs"][0] == {"artifact_count": 2}
        assert "s3://internal-workspace/foreign.txt" not in json.dumps(run.output)


@pytest.mark.asyncio
async def test_hermes_dispatch_sends_execution_context_outside_user_messages(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()  # start node
    assert await scheduler.run_once()  # Hermes dispatch

    async with workflow_sessions() as session:
        attempt = await session.scalar(
            select(WorkflowNodeAttempt)
            .where(WorkflowNodeAttempt.workflow_run_id == run_id)
            .where(WorkflowNodeAttempt.execution_id.is_not(None))
        )
        assert attempt is not None
        assert len(_FakeGateway.create_call_args) == 1
        args, kwargs = _FakeGateway.create_call_args[0]
        assert kwargs["session_id"] == attempt.execution_id
        assert attempt.execution_id in str(kwargs["instructions"])
        workspace_token = workspace_token_for_execution(
            execution_id=attempt.execution_id,
            instance_id=str(attempt.executor_instance_id),
        )
        assert workspace_token in str(kwargs["instructions"])
        assert attempt.execution_id not in str(args[0])
        assert workspace_token not in str(args[0])


@pytest.mark.asyncio
async def test_ambiguous_create_marks_node_uncertain_without_retry(
    workflow_sessions, monkeypatch
):
    _reset_gateway(create_payload=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)

    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and agent is not None
        assert run.status == "attention_required"
        assert agent.status == "uncertain"
        assert _FakeGateway.create_calls == 1


@pytest.mark.asyncio
async def test_known_run_monitor_recovers_expired_lease_without_new_dispatch(
    workflow_sessions, monkeypatch
):
    _reset_gateway(monitor_payload={"status": "running"})
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with workflow_sessions() as session:
        job = await session.scalar(
            select(WorkflowJob).where(
                WorkflowJob.workflow_run_id == run_id,
                WorkflowJob.job_type == "monitor_hermes",
            )
        )
        assert job is not None
        job.status = "running"
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    assert await scheduler.run_once()
    assert _FakeGateway.create_calls == 1
    assert _FakeGateway.monitor_calls == ["hermes-1"]


@pytest.mark.asyncio
async def test_requires_action_requires_human_attention(workflow_sessions, monkeypatch):
    _reset_gateway(monitor_payload={"status": "requires_action"})
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    assert await scheduler.run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and agent is not None
        assert run.status == "attention_required"
        assert agent.status == "uncertain"


@pytest.mark.asyncio
async def test_stop_failure_marks_active_cancel_as_unconfirmed(
    workflow_sessions, monkeypatch
):
    _reset_gateway(
        monitor_payload={"status": "running"},
        stop_error=httpx.RequestError("stop lost"),
    )
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        await WorkflowEngine(session).request_cancel(run=run, requested_by=tenant_id)
        await session.commit()

    assert await scheduler.run_once()  # monitor -> running and delayed
    assert await scheduler.run_once()  # cancel -> stop request error

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and agent is not None
        assert run.status == "attention_required"
        assert agent.status == "stop_unconfirmed"


@pytest.mark.asyncio
async def test_cancelled_attempt_ignores_late_hermes_success_dataflow(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition = _linear_definition(instance_id=instance_id)
    definition["variables"] = {"summary": {"type": "string"}}
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions, definition, with_instance=True
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # Hermes dispatch

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        monitor_job = await session.scalar(
            select(WorkflowJob).where(
                WorkflowJob.workflow_run_id == run_id,
                WorkflowJob.job_type == "monitor_hermes",
            )
        )
        assert run is not None and attempt is not None and agent is not None
        assert monitor_job is not None
        write = WorkflowVariableWrite(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            scope_run_id=agent.scope_run_id,
            node_run_id=agent.id,
            attempt_id=attempt.id,
            name="summary",
            value="late value",
        )
        decision = WorkflowControlDecision(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            scope_run_id=agent.scope_run_id,
            attempt_id=attempt.id,
            target_node_run_id=agent.id,
            kind="condition",
            token=uuid4().hex,
            allowed_ports=["approved", "rejected"],
            value="approved",
            status="submitted",
        )
        session.add_all([write, decision])
        await session.flush()
        await WorkflowEngine(session).request_cancel(run=run, requested_by=tenant_id)
        monitor_job.status = "running"
        monitor_job.fencing_token = 1
        monitor = HermesMonitor(
            job_id=monitor_job.id,
            fencing_token=1,
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            node_run_id=agent.id,
            attempt_id=attempt.id,
            base_url="http://unused",
            api_key="",
            external_run_id=str(attempt.external_run_id),
        )
        await WorkflowEngine(session).persist_monitor_result(
            monitor=monitor,
            payload={"status": "succeeded", "output": {"summary": "late"}},
        )
        await session.commit()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        write = await session.scalar(
            select(WorkflowVariableWrite).where(
                WorkflowVariableWrite.workflow_run_id == run_id
            )
        )
        decision = await session.scalar(
            select(WorkflowControlDecision).where(
                WorkflowControlDecision.workflow_run_id == run_id
            )
        )
        outputs = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.kind == "system_output",
                    )
                )
            ).all()
        )
        assert run is not None and agent is not None and attempt is not None
        assert write is not None and decision is not None
        assert run.status == "cancelled"
        assert run.output == {"final_artifact_ids": []}
        assert agent.status == "cancelled"
        assert agent.output is None
        assert attempt.status == "cancelled"
        assert write.status == "discarded"
        assert decision.status == "discarded"
        assert outputs == []


@pytest.mark.asyncio
async def test_v1_dispatch_job_is_aborted_without_calling_hermes(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    _, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=False
    )

    assert await WorkflowScheduler(workflow_sessions).run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        job = await session.scalar(
            select(WorkflowJob).where(WorkflowJob.workflow_run_id == run_id)
        )
        assert run is not None and node is not None and job is not None
        assert run.status == "failed"
        assert run.attention_reason == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert node.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert job.status == "succeeded"
        assert _FakeGateway.create_calls == 0


@pytest.mark.asyncio
async def test_v1_monitor_callback_is_aborted_without_materializing_output(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    _, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=True
    )

    assert await WorkflowScheduler(workflow_sessions).run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        outputs = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.kind == "system_output",
                    )
                )
            ).all()
        )
        cancel_job = await session.scalar(
            select(WorkflowJob).where(
                WorkflowJob.workflow_run_id == run_id,
                WorkflowJob.job_type == "cancel_hermes",
            )
        )
        assert run is not None
        assert run.status == "failed"
        assert outputs == []
        assert cancel_job is not None and cancel_job.status == "queued"
        assert _FakeGateway.monitor_calls == []


@pytest.mark.asyncio
async def test_v1_cancel_audits_stop_failure_without_reviving_legacy_run(
    workflow_sessions, monkeypatch
):
    _reset_gateway(stop_error=httpx.ReadTimeout("legacy stop timeout"))
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=True
    )

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        await WorkflowEngine(session).request_cancel(run=run, requested_by=tenant_id)
        await session.commit()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        assert run is not None and node is not None and attempt is not None
        assert run.status == "failed"
        assert run.attention_reason == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert node.status == "stop_requested"
        assert attempt.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        stop_event = await session.scalar(
            select(WorkflowEvent).where(
                WorkflowEvent.workflow_run_id == run_id,
                WorkflowEvent.event_type == "node.stop_unconfirmed",
            )
        )
        assert run is not None and node is not None and attempt is not None
        assert run.status == "failed"
        assert run.attention_reason == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert node.status == "stop_unconfirmed"
        assert node.error_code == "STOP_UNCONFIRMED"
        assert attempt.status == "stop_unconfirmed"
        assert stop_event is not None
        assert stop_event.data["code"] == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert _FakeGateway.monitor_calls == []


@pytest.mark.asyncio
async def test_v1_run_rejects_public_artifact_upload_before_reserving_storage(
    workflow_sessions,
):
    tenant_id, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=False
    )

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workflow_routes.upload_workflow_artifact(
                run_id=run_id,
                file=UploadFile(filename="legacy.txt", file=BytesIO(b"legacy")),
                node_run_id=None,
                session=session,
                tenant_id=tenant_id,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "WORKFLOW_DSL_V1_UNSUPPORTED"
        run = await session.get(WorkflowRun, run_id)
        artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id
                    )
                )
            ).all()
        )
        assert run is not None
        assert run.budget == {}
        assert artifacts == []


@pytest.mark.asyncio
async def test_v1_run_rejects_manual_mutations_without_changing_persisted_state(
    workflow_sessions,
):
    _tenant_id, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=False
    )
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        assert run is not None and node is not None
        run.status = "attention_required"
        node.status = "uncertain"
        await session.commit()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        assert run is not None and node is not None
        engine = WorkflowEngine(session)
        with pytest.raises(WorkflowEngineError, match="WORKFLOW_DSL_V1_UNSUPPORTED"):
            await engine.retry_uncertain(run=run, node=node)
        with pytest.raises(WorkflowEngineError, match="WORKFLOW_DSL_V1_UNSUPPORTED"):
            await engine.resolve_uncertain_as_failed(
                run=run,
                node=node,
                reason="不应修改历史版本",
            )
        await session.commit()

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        events = list(
            (
                await session.scalars(
                    select(WorkflowEvent).where(WorkflowEvent.workflow_run_id == run_id)
                )
            ).all()
        )
        assert run is not None and node is not None
        assert run.status == "attention_required"
        assert node.status == "uncertain"
        assert events == []


@pytest.mark.asyncio
async def test_artifact_upload_enforces_run_budget(
    workflow_sessions, tmp_path, monkeypatch
):
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions, _linear_definition(artifact_limit=3)
    )
    monkeypatch.setattr(workflow_routes, "artifact_store", LocalArtifactStore(tmp_path))

    async with workflow_sessions() as session:
        result = await workflow_routes.upload_workflow_artifact(
            run_id=run_id,
            file=UploadFile(filename="first.txt", file=BytesIO(b"abc")),
            node_run_id=None,
            session=session,
            tenant_id=tenant_id,
        )
        assert result.data["size_bytes"] == 3

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workflow_routes.upload_workflow_artifact(
                run_id=run_id,
                file=UploadFile(filename="second.txt", file=BytesIO(b"d")),
                node_run_id=None,
                session=session,
                tenant_id=tenant_id,
            )
        assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_local_artifact_download_returns_file_response(
    workflow_sessions, tmp_path, monkeypatch
):
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions, _linear_definition(artifact_limit=1024)
    )
    store = LocalArtifactStore(tmp_path)
    monkeypatch.setattr(workflow_routes, "artifact_store", store)

    async with workflow_sessions() as session:
        uploaded = await workflow_routes.upload_workflow_artifact(
            run_id=run_id,
            file=UploadFile(filename="download.txt", file=BytesIO(b"download body")),
            node_run_id=None,
            session=session,
            tenant_id=tenant_id,
        )
        artifact_id = UUID(str(uploaded.data["id"]))
        artifact = await session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        path = await store.file_path(artifact.uri)

    async with workflow_sessions() as session:
        response = await workflow_routes.download_workflow_artifact(
            run_id=run_id,
            artifact_id=artifact_id,
            session=session,
            tenant_id=tenant_id,
        )

    assert isinstance(response, FileResponse)
    assert response.path == path
    assert response.media_type == "text/plain"


@pytest.mark.asyncio
async def test_artifact_upload_persists_reservation_before_staging(
    workflow_sessions, tmp_path, monkeypatch
):
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions, _linear_definition(artifact_limit=3)
    )

    class ObservingStore(LocalArtifactStore):
        def __init__(self) -> None:
            super().__init__(tmp_path)
            self.observed = False

        async def stage_stream(self, **kwargs):
            artifact_id = kwargs["artifact_id"]
            async with workflow_sessions() as observed_session:
                artifact = await observed_session.get(WorkflowArtifact, artifact_id)
                run = await observed_session.get(WorkflowRun, run_id)
                assert artifact is not None and run is not None
                assert artifact.status == "uploading"
                assert artifact.uri == "staged://pending"
                assert artifact.size_bytes == 3
                assert run.budget["artifact_staged_bytes"] == 3
            self.observed = True
            raise ArtifactStoreError("simulated stream failure")

    store = ObservingStore()
    monkeypatch.setattr(workflow_routes, "artifact_store", store)
    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workflow_routes.upload_workflow_artifact(
                run_id=run_id,
                file=UploadFile(filename="interrupted.txt", file=BytesIO(b"abc")),
                node_run_id=None,
                session=session,
                tenant_id=tenant_id,
            )
        assert exc_info.value.status_code == 413
    assert store.observed
    async with workflow_sessions() as session:
        artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.kind == "user",
                    )
                )
            ).all()
        )
        run = await session.get(WorkflowRun, run_id)
        assert artifacts == []
        assert run is not None
        assert run.budget["artifact_staged_bytes"] == 0


@pytest.mark.asyncio
async def test_agent_input_snapshot_is_workspace_and_variable_projection(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition = _linear_definition(instance_id=instance_id)
    definition["variables"] = {"approved": {"type": "boolean"}}
    _, run_id, _ = await _create_run(workflow_sessions, definition, with_instance=True)

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start -> Agent ready

    async with workflow_sessions() as session:
        agent = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert agent is not None and agent.input_snapshot is not None
        assert agent.input_snapshot["variables"] == {}
        assert agent.input_snapshot["system"]["artifact_count"] == 1
        assert agent.input_snapshot["artifacts"][0]["name"] == "workflow-input.json"


@pytest.mark.asyncio
async def test_hermes_result_is_materialized_as_managed_system_artifact(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # Hermes dispatch
    assert await scheduler.run_once()  # Hermes success

    async with workflow_sessions() as session:
        artifact = await session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.kind == "system_output",
            )
        )
        assert artifact is not None
        assert artifact.name == "node-output.json"
        assert artifact.status == "available"


@pytest.mark.asyncio
async def test_node_debug_run_isolated_from_business_dag(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, business_run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )

    async with workflow_sessions() as session:
        business_run = await session.get(WorkflowRun, business_run_id)
        assert business_run is not None
        workflow = await session.get(Workflow, business_run.workflow_id)
        version = await session.get(WorkflowVersion, business_run.workflow_version_id)
        assert workflow is not None and version is not None
        debug_run = await WorkflowEngine(session).create_node_debug_run(
            tenant_id=tenant_id,
            workflow=workflow,
            version=version,
            node_id=AGENT_NODE_ID,
            node_input={"topic": "debug"},
        )
        business_nodes_before = {
            node.id: (node.status, node.output)
            for node in (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == business_run_id
                    )
                )
            ).all()
        }
        business_edges_before = {
            edge.id: edge.status
            for edge in (
                await session.scalars(
                    select(WorkflowEdgeRun).where(
                        WorkflowEdgeRun.workflow_run_id == business_run_id
                    )
                )
            ).all()
        }
        business_jobs = list(
            (
                await session.scalars(
                    select(WorkflowJob).where(
                        WorkflowJob.workflow_run_id == business_run_id
                    )
                )
            ).all()
        )
        for job in business_jobs:
            job.available_at = utcnow() + timedelta(minutes=5)
        await session.commit()
        debug_run_id = debug_run.id

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # Debug Hermes dispatch
    assert await scheduler.run_once()  # Debug Hermes monitor -> complete

    async with workflow_sessions() as session:
        debug_run = await session.get(WorkflowRun, debug_run_id)
        debug_nodes = list(
            (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == debug_run_id
                    )
                )
            ).all()
        )
        debug_edges = list(
            (
                await session.scalars(
                    select(WorkflowEdgeRun).where(
                        WorkflowEdgeRun.workflow_run_id == debug_run_id
                    )
                )
            ).all()
        )
        business_nodes_after = {
            node.id: (node.status, node.output)
            for node in (
                await session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == business_run_id
                    )
                )
            ).all()
        }
        business_edges_after = {
            edge.id: edge.status
            for edge in (
                await session.scalars(
                    select(WorkflowEdgeRun).where(
                        WorkflowEdgeRun.workflow_run_id == business_run_id
                    )
                )
            ).all()
        }
        assert debug_run is not None
        assert debug_run.run_kind == "node_debug"
        assert debug_run.debug_node_id == AGENT_NODE_ID
        assert debug_run.status == "succeeded"
        assert debug_run.output is not None
        assert debug_run.output["final_artifact_ids"] == []
        assert debug_run.output["node_output"]["node_output"]["name"] == (
            "node-output.json"
        )
        assert [node.node_definition_id for node in debug_nodes] == [AGENT_NODE_ID]
        assert debug_nodes[0].status == "succeeded"
        assert debug_edges == []
        assert business_nodes_after == business_nodes_before
        assert business_edges_after == business_edges_before


@pytest.mark.asyncio
async def test_node_debug_run_accepts_untyped_input(workflow_sessions):
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition = _linear_definition(instance_id=instance_id)
    tenant_id, business_run_id, _ = await _create_run(workflow_sessions, definition)

    async with workflow_sessions() as session:
        business_run = await session.get(WorkflowRun, business_run_id)
        assert business_run is not None
        workflow = await session.get(Workflow, business_run.workflow_id)
        version = await session.get(WorkflowVersion, business_run.workflow_version_id)
        assert workflow is not None and version is not None
        runs_before = list(
            (
                await session.scalars(
                    select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id)
                )
            ).all()
        )
        debug_run = await WorkflowEngine(session).create_node_debug_run(
            tenant_id=tenant_id,
            workflow=workflow,
            version=version,
            node_id=AGENT_NODE_ID,
            node_input={},
        )
        runs_after = list(
            (
                await session.scalars(
                    select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id)
                )
            ).all()
        )
        assert debug_run.run_kind == "node_debug"
        assert len(runs_after) == len(runs_before) + 1

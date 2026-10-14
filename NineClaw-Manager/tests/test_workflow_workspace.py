"""Manager workspace bridge authorization and Artifact lifecycle tests."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.api.routes import workflow_workspace as workspace_routes
from app.models.workflow import (
    WorkflowArtifact,
    WorkflowNodeAttempt,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.services.workflow.artifacts import LocalArtifactStore
from app.services.workflow import artifact_lifecycle
from app.services.workflow.engine import WorkflowEngine
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.workspace_auth import (
    bridge_token_for_instance,
    workspace_token_for_execution,
)
from app.schemas.instance import _safe_instance_config
from app.services.instance_service import (
    _build_workspace_bridge_env,
    _persisted_instance_environment,
)
from app.core.config import settings
from app.services.workflow import scheduler as scheduler_module

from test_workflow_runtime import (
    AGENT_NODE_ID,
    END_NODE_ID,
    START_NODE_ID,
    WORKFLOW_TEST_DATABASE_URL,
    _FakeGateway,
    _create_legacy_v1_run,
    _create_run,
    _linear_definition,
    _reset_gateway,
    workflow_sessions,
)


SOURCE_NODE_ID = "hermes_agent_0000000000004008"
TARGET_NODE_ID = "hermes_agent_0000000000004009"


@pytest.fixture(autouse=True)
def _skip_database_dependent_workspace_tests(request):
    if "workflow_sessions" in request.fixturenames and not WORKFLOW_TEST_DATABASE_URL:
        pytest.skip("需要 WORKFLOW_TEST_DATABASE_URL 指向已迁移的 PostgreSQL")


@pytest.fixture(autouse=True)
def _workspace_bridge_secret(monkeypatch):
    monkeypatch.setattr(settings, "workflow_workspace_bridge_secret", "test-secret")


def _workspace_token(attempt: WorkflowNodeAttempt, instance_id: str) -> str:
    return workspace_token_for_execution(
        execution_id=attempt.execution_id,
        instance_id=instance_id,
    )


def _two_agent_definition(instance_id: str) -> dict:
    return {
        "schema_version": 2,
        "nodes": [
            {"id": START_NODE_ID, "type": "start"},
            {
                "id": SOURCE_NODE_ID,
                "type": "hermes_agent",
                "config": {"instance_id": instance_id, "prompt": "生成文件"},
            },
            {
                "id": TARGET_NODE_ID,
                "type": "hermes_agent",
                "config": {"instance_id": instance_id, "prompt": "读取文件"},
            },
            {"id": END_NODE_ID, "type": "end"},
        ],
        "edges": [
            {
                "id": "start-source",
                "source_node_id": START_NODE_ID,
                "target_node_id": SOURCE_NODE_ID,
            },
            {
                "id": "source-target",
                "source_node_id": SOURCE_NODE_ID,
                "target_node_id": TARGET_NODE_ID,
            },
            {
                "id": "target-end",
                "source_node_id": TARGET_NODE_ID,
                "target_node_id": END_NODE_ID,
            },
        ],
        "limits": {"max_artifact_bytes": 1024, "max_hermes_runs": 3},
    }


async def _dispatch_active_attempt(
    workflow_sessions, instance_id: str
) -> tuple[UUID, WorkflowNodeAttempt]:
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    for _ in range(12):
        assert await scheduler.run_once()
        async with workflow_sessions() as session:
            attempt = await session.scalar(
                select(WorkflowNodeAttempt).where(
                    WorkflowNodeAttempt.workflow_run_id == run_id
                )
            )
            if attempt is not None and attempt.status == "dispatched":
                return run_id, attempt
    raise AssertionError("Hermes Attempt 未进入 dispatched 状态")


async def _stage_and_commit(
    workflow_sessions,
    *,
    attempt: WorkflowNodeAttempt,
    instance_id: str,
    content: bytes = b"workspace artifact",
) -> UUID:
    workspace_token = _workspace_token(attempt, instance_id)
    async with workflow_sessions() as session:
        staged = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="output.txt", file=BytesIO(content)),
            session=session,
            instance_id=instance_id,
            workspace_token=workspace_token,
        )
        artifact_id = UUID(str(staged["data"]["artifact_id"]))
    async with workflow_sessions() as session:
        committed = await workspace_routes.commit_workspace_upload(
            artifact_id=artifact_id,
            execution_id=attempt.execution_id,
            session=session,
            instance_id=instance_id,
            workspace_token=workspace_token,
        )
        assert committed["data"]["size_bytes"] == len(content)
    return artifact_id


@pytest.mark.asyncio
async def test_bridge_rejects_other_run_artifact_and_exposes_no_metadata(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    monkeypatch.setattr(
        artifact_lifecycle, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, first_attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    artifact_id = await _stage_and_commit(
        workflow_sessions, attempt=first_attempt, instance_id=instance_id
    )
    second_instance_id = f"agent-{uuid4().hex[:16]}"
    _, second_attempt = await _dispatch_active_attempt(
        workflow_sessions, second_instance_id
    )

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.download_workspace_artifact(
                artifact_id=artifact_id,
                execution_id=second_attempt.execution_id,
                session=session,
                instance_id=second_instance_id,
                workspace_token=_workspace_token(second_attempt, second_instance_id),
            )
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_bridge_rejects_other_active_execution_token_on_same_instance(
    workflow_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition = _two_agent_definition(instance_id)
    definition["edges"] = [
        {
            "id": "start-source",
            "source_node_id": START_NODE_ID,
            "target_node_id": SOURCE_NODE_ID,
        },
        {
            "id": "start-target",
            "source_node_id": START_NODE_ID,
            "target_node_id": TARGET_NODE_ID,
        },
        {
            "id": "source-end",
            "source_node_id": SOURCE_NODE_ID,
            "target_node_id": END_NODE_ID,
        },
        {
            "id": "target-end",
            "source_node_id": TARGET_NODE_ID,
            "target_node_id": END_NODE_ID,
        },
    ]
    _, run_id, _ = await _create_run(workflow_sessions, definition, with_instance=True)
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # first Agent dispatch
    assert await scheduler.run_once()  # second Agent dispatch
    async with workflow_sessions() as session:
        attempts = list(
            (
                await session.scalars(
                    select(WorkflowNodeAttempt)
                    .where(
                        WorkflowNodeAttempt.workflow_run_id == run_id,
                        WorkflowNodeAttempt.status == "dispatched",
                    )
                    .order_by(WorkflowNodeAttempt.created_at)
                )
            ).all()
        )
        assert len(attempts) == 2
        first_attempt, second_attempt = attempts

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.list_workspace_artifacts(
                execution_id=first_attempt.execution_id,
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(second_attempt, instance_id),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_workspace_commit_remains_available_after_successful_node(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    artifact_id = await _stage_and_commit(
        workflow_sessions, attempt=attempt, instance_id=instance_id
    )

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # monitor -> Hermes succeeded
    assert await scheduler.run_once()  # end

    async with workflow_sessions() as session:
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert node is not None and node.output is not None
        artifact = await session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        assert artifact.status == "available"
        assert artifact.kind == "user"
        assert node.output["node_output"]["name"] == "node-output.json"


@pytest.mark.asyncio
async def test_uncommitted_upload_is_discarded_when_attempt_succeeds(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    monkeypatch.setattr(
        artifact_lifecycle, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    async with workflow_sessions() as session:
        staged = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="uncommitted.txt", file=BytesIO(b"temporary")),
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
        artifact_id = UUID(str(staged["data"]["artifact_id"]))

    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # monitor -> Hermes succeeded
    async with workflow_sessions() as session:
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert node is not None and node.output is not None
        assert node.output["node_output"]["name"] == "node-output.json"
        assert await session.get(WorkflowArtifact, artifact_id) is None
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_selected_downstream_node_can_download_only_committed_input_artifact(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, run_id, _ = await _create_run(
        workflow_sessions,
        _two_agent_definition(instance_id),
        with_instance=True,
    )
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # source dispatch
    async with workflow_sessions() as session:
        source_attempt = await session.scalar(
            select(WorkflowNodeAttempt)
            .join(WorkflowNodeRun)
            .where(
                WorkflowNodeAttempt.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == SOURCE_NODE_ID,
            )
        )
        assert source_attempt is not None
    artifact_id = await _stage_and_commit(
        workflow_sessions,
        attempt=source_attempt,
        instance_id=instance_id,
        content=b"selected edge input",
    )
    assert await scheduler.run_once()  # source monitor -> target ready
    assert await scheduler.run_once()  # target dispatch
    async with workflow_sessions() as session:
        target_attempt = await session.scalar(
            select(WorkflowNodeAttempt)
            .join(WorkflowNodeRun)
            .where(
                WorkflowNodeAttempt.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == TARGET_NODE_ID,
            )
        )
        target = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == TARGET_NODE_ID,
            )
        )
        assert target_attempt is not None and target is not None
        assert target.input_snapshot is not None
        assert str(artifact_id) in target.input_snapshot["artifact_ids"]
        assert {item["name"] for item in target.input_snapshot["artifacts"]} >= {
            "workflow-input.json",
            "node-output.json",
            "output.txt",
        }
        response = await workspace_routes.download_workspace_artifact(
            artifact_id=artifact_id,
            execution_id=target_attempt.execution_id,
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(target_attempt, instance_id),
        )
        assert (
            b"".join([chunk async for chunk in response.body_iterator])
            == b"selected edge input"
        )


@pytest.mark.asyncio
async def test_failed_hermes_reclaims_artifact_before_downstream_use(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway(monitor_payload={"status": "failed", "error": "执行失败"})
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    monkeypatch.setattr(
        artifact_lifecycle, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition = _two_agent_definition(instance_id)
    _, run_id, _ = await _create_run(workflow_sessions, definition, with_instance=True)
    scheduler = WorkflowScheduler(workflow_sessions)
    assert await scheduler.run_once()  # start
    assert await scheduler.run_once()  # source dispatch
    async with workflow_sessions() as session:
        source_attempt = await session.scalar(
            select(WorkflowNodeAttempt)
            .join(WorkflowNodeRun)
            .where(
                WorkflowNodeAttempt.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == SOURCE_NODE_ID,
            )
        )
        assert source_attempt is not None
    artifact_id = await _stage_and_commit(
        workflow_sessions,
        attempt=source_attempt,
        instance_id=instance_id,
        content=b"must-not-propagate",
    )

    assert await scheduler.run_once()  # source failure

    async with workflow_sessions() as session:
        source = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == SOURCE_NODE_ID,
            )
        )
        target = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == TARGET_NODE_ID,
            )
        )
        target_attempts = list(
            (
                await session.scalars(
                    select(WorkflowNodeAttempt)
                    .join(WorkflowNodeRun)
                    .where(
                        WorkflowNodeAttempt.workflow_run_id == run_id,
                        WorkflowNodeRun.node_definition_id == TARGET_NODE_ID,
                    )
                )
            ).all()
        )
        assert source is not None and target is not None
        assert source.status == "failed"
        assert source.error_code == "HERMES_RUN_FAILED"
        assert source.output is None
        assert target.status == "blocked"
        assert target_attempts == []
        assert await session.get(WorkflowArtifact, artifact_id) is None
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


@pytest.mark.asyncio
async def test_cancelled_attempt_cannot_commit_staged_artifact(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    monkeypatch.setattr(
        artifact_lifecycle, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)

    async with workflow_sessions() as session:
        staged = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="late.txt", file=BytesIO(b"late")),
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
        artifact_id = UUID(str(staged["data"]["artifact_id"]))

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        await WorkflowEngine(session).request_cancel(run=run, requested_by="tester")
        await session.commit()

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.commit_workspace_upload(
                artifact_id=artifact_id,
                execution_id=attempt.execution_id,
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 409
        artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.created_by_attempt_id == attempt.id,
                        WorkflowArtifact.status == "available",
                    )
                )
            ).all()
        )
        assert artifacts == []
        assert await session.get(WorkflowArtifact, artifact_id) is None
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_retried_attempt_cannot_commit_old_staged_artifact(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    monkeypatch.setattr(
        artifact_lifecycle, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    async with workflow_sessions() as session:
        staged = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="old.txt", file=BytesIO(b"old")),
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
        artifact_id = UUID(str(staged["data"]["artifact_id"]))

    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        current_attempt = await session.get(WorkflowNodeAttempt, attempt.id)
        assert run is not None and node is not None and current_attempt is not None
        run.status = "attention_required"
        node.status = "uncertain"
        current_attempt.status = "uncertain"
        await session.flush()
        await WorkflowEngine(session).retry_uncertain(run=run, node=node)
        await session.commit()

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.commit_workspace_upload(
                artifact_id=artifact_id,
                execution_id=attempt.execution_id,
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 409
        assert await session.get(WorkflowArtifact, artifact_id) is None
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_uncertain_attempt_stays_workspace_revoked_after_manual_bind(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    _, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    async with workflow_sessions() as session:
        current_attempt = await session.get(WorkflowNodeAttempt, attempt.id)
        assert current_attempt is not None
        current_attempt.error_code = "HERMES_DISPATCH_UNKNOWN"
        await session.commit()

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.stage_workspace_upload(
                execution_id=attempt.execution_id,
                file=UploadFile(filename="late.txt", file=BytesIO(b"late")),
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_workspace_over_budget_discards_staged_file_and_metadata(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)

    async with workflow_sessions() as session:
        staged = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="too-big.txt", file=BytesIO(b"four")),
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
        artifact_id = UUID(str(staged["data"]["artifact_id"]))

    # A concurrent Artifact commit can consume the budget after staging. Commit
    # must re-check and still clean the stale staging file and DB metadata.
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        run.budget = {**run.budget, "max_artifact_bytes": 3}
        await session.commit()

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.commit_workspace_upload(
                artifact_id=artifact_id,
                execution_id=attempt.execution_id,
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 413
        assert await session.get(WorkflowArtifact, artifact_id) is None
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_workspace_stage_rejects_known_remaining_budget(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        run.budget = {**run.budget, "max_artifact_bytes": 3}
        await session.commit()

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.stage_workspace_upload(
                execution_id=attempt.execution_id,
                file=UploadFile(filename="too-big.txt", file=BytesIO(b"four")),
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 413
        artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.created_by_attempt_id == attempt.id,
                    )
                )
            ).all()
        )
        assert artifacts == []
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_staged_upload_reservation_blocks_concurrent_quota_overcommit(
    workflow_sessions, tmp_path, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    monkeypatch.setattr(
        workspace_routes, "artifact_store", LocalArtifactStore(tmp_path)
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    run_id, attempt = await _dispatch_active_attempt(workflow_sessions, instance_id)
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        run.budget = {**run.budget, "max_artifact_bytes": 3}
        await session.commit()

    async with workflow_sessions() as session:
        first = await workspace_routes.stage_workspace_upload(
            execution_id=attempt.execution_id,
            file=UploadFile(filename="first.txt", file=BytesIO(b"ab")),
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
        first_id = UUID(str(first["data"]["artifact_id"]))

    async with workflow_sessions() as session:
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.stage_workspace_upload(
                execution_id=attempt.execution_id,
                file=UploadFile(filename="second.txt", file=BytesIO(b"cd")),
                session=session,
                instance_id=instance_id,
                workspace_token=_workspace_token(attempt, instance_id),
            )
        assert exc_info.value.status_code == 413
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.budget["artifact_staged_bytes"] == 2
        staged = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.workflow_run_id == run_id,
                        WorkflowArtifact.status == "staged",
                    )
                )
            ).all()
        )
        assert [artifact.id for artifact in staged] == [first_id]

    async with workflow_sessions() as session:
        await workspace_routes.abort_workspace_upload(
            artifact_id=first_id,
            execution_id=attempt.execution_id,
            session=session,
            instance_id=instance_id,
            workspace_token=_workspace_token(attempt, instance_id),
        )
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_bridge_rejects_active_attempt_bound_to_v1_run(workflow_sessions):
    _tenant_id, run_id = await _create_legacy_v1_run(
        workflow_sessions, with_external_attempt=True
    )

    async with workflow_sessions() as session:
        attempt = await session.scalar(
            select(WorkflowNodeAttempt).where(
                WorkflowNodeAttempt.workflow_run_id == run_id
            )
        )
        assert attempt is not None
        with pytest.raises(HTTPException) as exc_info:
            await workspace_routes.list_workspace_artifacts(
                execution_id=attempt.execution_id,
                session=session,
                instance_id="legacy-instance",
                workspace_token=_workspace_token(attempt, "legacy-instance"),
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "WORKFLOW_DSL_V1_UNSUPPORTED"


@pytest.mark.asyncio
async def test_bridge_auth_uses_instance_scoped_token(monkeypatch):
    monkeypatch.setattr(settings, "workflow_workspace_bridge_secret", "test-secret")
    token = bridge_token_for_instance("instance-a")
    assert (
        await workspace_routes._require_bridge_instance(
            authorization=f"Bearer {token}", instance_id="instance-a"
        )
        == "instance-a"
    )
    with pytest.raises(HTTPException) as exc_info:
        await workspace_routes._require_bridge_instance(
            authorization=f"Bearer {token}", instance_id="instance-b"
        )
    assert exc_info.value.status_code == 401


def test_instance_creation_injects_scoped_bridge_environment(monkeypatch):
    monkeypatch.setattr(settings, "workflow_workspace_bridge_secret", "test-secret")
    monkeypatch.setattr(
        settings, "workflow_workspace_manager_url", "http://manager:8000/"
    )

    env = _build_workspace_bridge_env("instance-a")

    assert env == {
        "NINECLAW_MANAGER_URL": "http://manager:8000",
        "NINECLAW_WORKSPACE_INSTANCE_ID": "instance-a",
        "NINECLAW_WORKSPACE_BRIDGE_TOKEN": bridge_token_for_instance("instance-a"),
        "NINECLAW_WORKSPACE_DIR": "/tmp/nineclaw-workspace",
    }
    assert _persisted_instance_environment({"CUSTOM": "value", **env}) == {
        "CUSTOM": "value"
    }
    assert _safe_instance_config({"environment": {"CUSTOM": "value", **env}})[
        "environment"
    ] == {"CUSTOM": "value"}

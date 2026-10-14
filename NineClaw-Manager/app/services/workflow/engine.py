"""Persistent DAG runtime for workflow definitions.

The engine mutates database state only.  The scheduler owns job leases and
performs Hermes HTTP calls outside database transactions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.instance import ServiceInstance
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
from app.services.workflow.events import append_event
from app.services.workflow.artifact_lifecycle import invalidate_attempt_artifacts
from app.services.workflow.artifacts import ArtifactStoreError, artifact_store
from app.services.workflow.compiler import (
    WorkflowCompilationError,
    ensure_workflow_dsl_v2,
)
from app.services.workflow.expressions import ExpressionError, evaluate
from app.services.workflow.state import (
    ATTENTION_NODE_STATES,
    EDGE_BLOCKED,
    EDGE_NOT_SELECTED,
    EDGE_PENDING,
    EDGE_TAKEN,
    NODE_TERMINAL,
    is_node_terminal,
)
from app.services.workflow.workspace_auth import (
    WorkspaceBridgeConfigurationError,
    workspace_token_for_execution,
)


class WorkflowEngineError(RuntimeError):
    pass


class WorkflowSchemaValidationError(WorkflowEngineError):
    """Legacy public exception kept until callers stop importing it."""


class WorkflowFinalArtifactValidationError(WorkflowEngineError):
    """An automatically selected final Artifact is no longer available."""


class WorkflowVariableConflictError(WorkflowEngineError):
    """Two selected parallel paths produced incompatible variable values."""


@dataclass(frozen=True)
class HermesDispatch:
    job_id: UUID
    fencing_token: int
    tenant_id: str
    workflow_run_id: UUID
    node_run_id: UUID
    attempt_id: UUID
    base_url: str
    api_key: str
    model: str
    messages: list[dict[str, Any]]
    instructions: str
    session_id: str
    extra: dict[str, Any]


@dataclass(frozen=True)
class HermesMonitor:
    job_id: UUID
    fencing_token: int
    tenant_id: str
    workflow_run_id: UUID
    node_run_id: UUID
    attempt_id: UUID
    base_url: str
    api_key: str
    external_run_id: str


class WorkflowEngine:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(
        self,
        *,
        tenant_id: str,
        workflow: Workflow,
        version: WorkflowVersion,
        workflow_input: dict[str, Any],
    ) -> WorkflowRun:
        try:
            ensure_workflow_dsl_v2(version.definition)
        except WorkflowCompilationError as exc:
            raise WorkflowEngineError("WORKFLOW_DSL_V1_UNSUPPORTED") from exc
        plan = dict(version.compiled_plan)
        limits = dict(plan.get("limits") or {})
        budget = {
            **limits,
            "node_executions": 0,
            "hermes_runs": 0,
            "artifact_bytes": 0,
            "artifact_staged_bytes": 0,
        }
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            status="running",
            input=workflow_input,
            budget=budget,
            started_at=utcnow(),
        )
        self.session.add(run)
        await self.session.flush()
        workflow_input_artifact = await self._materialize_system_artifact(
            run=run,
            name="workflow-input.json",
            payload=workflow_input,
            kind="system_input",
        )
        scope = WorkflowScopeRun(
            tenant_id=tenant_id,
            workflow_run_id=run.id,
            kind="root",
            state={
                "plan": plan,
                "inherited_artifact_ids": [str(workflow_input_artifact.id)],
                "inherited_variable_state": {},
            },
        )
        self.session.add(scope)
        await self.session.flush()
        await self._materialize_scope(run=run, scope=scope, plan=plan)
        await append_event(
            self.session,
            run=run,
            event_type="workflow.started",
            data={
                "workflow_id": str(workflow.id),
                "version_number": version.version_number,
            },
        )
        start_id = str(plan["root_node_id"])
        start_node = await self._node(run.id, scope.id, start_id)
        await self._ready_node(
            run=run,
            scope=scope,
            node=start_node,
            input_snapshot=await self._resolve_input_snapshot(run, scope, start_node),
        )
        return run

    async def create_node_debug_run(
        self,
        *,
        tenant_id: str,
        workflow: Workflow,
        version: WorkflowVersion,
        node_id: str,
        node_input: dict[str, Any],
    ) -> WorkflowRun:
        """Create an isolated, scheduler-driven run for one published Hermes node."""
        try:
            ensure_workflow_dsl_v2(version.definition)
        except WorkflowCompilationError as exc:
            raise WorkflowEngineError("WORKFLOW_DSL_V1_UNSUPPORTED") from exc
        source_plan = dict(version.compiled_plan)
        source_nodes = source_plan.get("nodes")
        node_plan = (
            source_nodes.get(node_id) if isinstance(source_nodes, dict) else None
        )
        if not isinstance(node_plan, dict) or node_plan.get("type") != "hermes_agent":
            raise WorkflowEngineError("仅支持调试已发布版本中的顶层 Hermes 节点")
        debug_plan = {
            "engine_version": source_plan.get("engine_version", 2),
            "schema_version": 2,
            "root_node_id": node_id,
            "end_node_ids": [],
            "nodes": {node_id: json.loads(json.dumps(node_plan))},
            "edges": {},
            "adjacency": {node_id: []},
            "reverse_adjacency": {node_id: []},
            "outgoing_edge_ids": {node_id: []},
            "incoming_edge_ids": {node_id: []},
            "topological_order": [node_id],
            "limits": dict(source_plan.get("limits") or {}),
            "variables": dict(source_plan.get("variables") or {}),
            "join_policy": "all_resolved",
        }
        limits = dict(debug_plan["limits"])
        budget = {
            **limits,
            "node_executions": 0,
            "hermes_runs": 0,
            "artifact_bytes": 0,
            "artifact_staged_bytes": 0,
        }
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            run_kind="node_debug",
            debug_node_id=node_id,
            status="running",
            input=node_input,
            budget=budget,
            started_at=utcnow(),
        )
        self.session.add(run)
        await self.session.flush()
        workflow_input_artifact = await self._materialize_system_artifact(
            run=run,
            name="workflow-input.json",
            payload=node_input,
            kind="system_input",
        )
        scope = WorkflowScopeRun(
            tenant_id=tenant_id,
            workflow_run_id=run.id,
            kind="root",
            state={
                "plan": debug_plan,
                "inherited_artifact_ids": [str(workflow_input_artifact.id)],
                "inherited_variable_state": {},
            },
        )
        self.session.add(scope)
        await self.session.flush()
        await self._materialize_scope(run=run, scope=scope, plan=debug_plan)
        await append_event(
            self.session,
            run=run,
            event_type="workflow.started",
            data={
                "workflow_id": str(workflow.id),
                "version_number": version.version_number,
                "run_kind": "node_debug",
                "debug_node_id": node_id,
            },
        )
        node = await self._node(run.id, scope.id, node_id)
        await self._ready_node(
            run=run,
            scope=scope,
            node=node,
            input_snapshot=await self._resolve_input_snapshot(run, scope, node),
        )
        return run

    async def prepare_dispatch(
        self, *, job: WorkflowJob, fencing_token: int, worker_id: str
    ) -> HermesDispatch | None:
        """Prepare a node job.  Caller commits before making an external call."""
        if job.fencing_token != fencing_token or job.status != "running":
            return None
        if job.node_run_id is None or job.scope_run_id is None:
            await self._finish_job(job)
            return None
        run = await self._locked_run(job.workflow_run_id)
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return None
        node = await self._node_by_id(job.node_run_id)
        scope = await self._scope(job.scope_run_id)
        if run.cancel_requested_at is not None:
            if node.status == "dispatching" and node.active_attempt_id is not None:
                attempt = await self._attempt(node.active_attempt_id)
                if attempt.external_run_id is None:
                    await self._mark_uncertain(
                        run, node, attempt, "取消时 Hermes 派发结果未知"
                    )
                    await self._settle_hermes_reservation(run, created_or_unknown=True)
            else:
                await self._cancel_pending_node(run, scope, node, "工作流已请求取消")
            await self._finish_job(job)
            return None
        if node.status == "dispatching":
            # A lease expired after the attempt was prepared but before Hermes
            # returned a run id.  Starting again could duplicate tool effects.
            if node.active_attempt_id is not None:
                attempt = await self._attempt(node.active_attempt_id)
                if attempt.external_run_id is None:
                    await self._mark_uncertain(
                        run, node, attempt, "派发租约过期，Hermes 创建结果未知"
                    )
                    await self._settle_hermes_reservation(run, created_or_unknown=True)
            await self._finish_job(job)
            return None
        if node.status != "ready":
            await self._finish_job(job)
            return None
        if not await self._consume_node_budget(run):
            await self._fail_node(
                run, scope, node, "BUDGET_EXCEEDED", "工作流节点执行额度已耗尽"
            )
            await self._finish_job(job)
            return None
        node_plan = self._plan(scope)["nodes"][node.node_definition_id]
        if node.node_type == "hermes_agent":
            return await self._prepare_hermes(
                run, scope, node, node_plan, job, fencing_token, worker_id
            )
        await self._execute_local_node(run, scope, node, node_plan)
        await self._finish_job(job)
        return None

    async def persist_hermes_created(
        self,
        *,
        dispatch: HermesDispatch,
        external_run_id: str,
    ) -> None:
        job = await self._job(dispatch.job_id)
        node = await self._node_by_id(dispatch.node_run_id)
        attempt = await self._attempt(dispatch.attempt_id)
        run = await self._locked_run(dispatch.workflow_run_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if not await self._ensure_run_dsl_v2(run):
            await self._request_stop_for_unsupported_attempt(
                run=run,
                node=node,
                attempt=attempt,
                external_run_id=external_run_id,
            )
            await self._finish_job(job)
            return
        if node.active_attempt_id != attempt.id or attempt.status != "dispatching":
            return
        attempt.external_run_id = external_run_id
        attempt.status = "dispatched"
        attempt.updated_at = utcnow()
        cancellation_requested = run.cancel_requested_at is not None
        node.status = "stop_requested" if cancellation_requested else "running"
        node.updated_at = utcnow()
        await self._settle_hermes_reservation(run, created_or_unknown=True)
        await self._enqueue_job(
            run=run,
            scope_run_id=node.scope_run_id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            job_type="monitor_hermes",
            dedupe_key=f"monitor:{attempt.id}",
            payload={},
        )
        await append_event(
            self.session,
            run=run,
            event_type="node.started",
            data={
                "node_run_id": str(node.id),
                "node_id": node.node_definition_id,
                "external_run_id": external_run_id,
            },
        )
        if cancellation_requested:
            await self._enqueue_job(
                run=run,
                scope_run_id=node.scope_run_id,
                node_run_id=node.id,
                attempt_id=attempt.id,
                job_type="cancel_hermes",
                dedupe_key=f"cancel:{attempt.id}",
                payload={},
            )
            await append_event(
                self.session,
                run=run,
                event_type="node.stop_requested",
                data={"node_run_id": str(node.id), "node_id": node.node_definition_id},
            )
        await self._finish_job(job)

    async def persist_hermes_uncertain(
        self, *, dispatch: HermesDispatch, error: str
    ) -> None:
        job = await self._job(dispatch.job_id)
        node = await self._node_by_id(dispatch.node_run_id)
        attempt = await self._attempt(dispatch.attempt_id)
        run = await self._locked_run(dispatch.workflow_run_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return
        if node.active_attempt_id == attempt.id and attempt.external_run_id is None:
            await self._mark_uncertain(run, node, attempt, error)
            await self._settle_hermes_reservation(run, created_or_unknown=True)
        await self._finish_job(job)

    async def persist_hermes_rejected(
        self, *, dispatch: HermesDispatch, error: str
    ) -> None:
        """Persist a definite pre-dispatch rejection such as HTTP 401/422."""
        job = await self._job(dispatch.job_id)
        node = await self._node_by_id(dispatch.node_run_id)
        attempt = await self._attempt(dispatch.attempt_id)
        run = await self._locked_run(dispatch.workflow_run_id)
        scope = await self._scope(node.scope_run_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return
        if node.active_attempt_id == attempt.id and attempt.external_run_id is None:
            attempt.status = "failed"
            attempt.error_code = "HERMES_CREATE_REJECTED"
            attempt.error_message = error[:2048]
            attempt.finished_at = utcnow()
            await self._invalidate_attempt_artifacts(run, attempt)
            await self._fail_node(run, scope, node, "HERMES_CREATE_REJECTED", error)
            await self._settle_hermes_reservation(run, created_or_unknown=False)
        await self._finish_job(job)

    async def prepare_monitor(
        self, *, job: WorkflowJob, fencing_token: int
    ) -> HermesMonitor | None:
        if (
            job.fencing_token != fencing_token
            or job.status != "running"
            or job.attempt_id is None
        ):
            return None
        run = await self._locked_run(job.workflow_run_id)
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return None
        attempt = await self._attempt(job.attempt_id)
        node = await self._node_by_id(attempt.node_run_id)
        if attempt.external_run_id is None:
            await self._mark_uncertain(run, node, attempt, "监控任务缺少 Hermes run_id")
            await self._finish_job(job)
            return None
        if (
            node.active_attempt_id != attempt.id
            or attempt.status != "dispatched"
            or node.status not in {"running", "stop_requested"}
        ):
            await self._finish_job(job)
            return None
        node_plan = self._plan(await self._scope(node.scope_run_id))["nodes"][
            node.node_definition_id
        ]
        base_url = self._gateway_base_url(str(node_plan["config"]["instance_id"]))
        return HermesMonitor(
            job_id=job.id,
            fencing_token=fencing_token,
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            base_url=base_url,
            api_key=settings.nineclaw_token,
            external_run_id=attempt.external_run_id,
        )

    async def persist_monitor_result(
        self, *, monitor: HermesMonitor, payload: dict[str, Any]
    ) -> None:
        run = await self._locked_run(monitor.workflow_run_id)
        job = await self._job(monitor.job_id)
        attempt = await self._attempt(monitor.attempt_id)
        node = await self._node_by_id(monitor.node_run_id)
        scope = await self._scope(node.scope_run_id)
        if job.status != "running" or job.fencing_token != monitor.fencing_token:
            return
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return
        if (
            node.active_attempt_id != attempt.id
            or attempt.status != "dispatched"
            or node.status not in {"running", "stop_requested"}
        ):
            await append_event(
                self.session,
                run=run,
                event_type="attempt.result_ignored",
                data={"attempt_id": str(attempt.id), "reason": "attempt_not_active"},
            )
            await self._finish_job(job)
            return
        remote_status = _remote_status(payload)
        if remote_status in {"requires_action", "waiting_approval"}:
            await self._mark_attention(
                run,
                node,
                attempt,
                "HERMES_APPROVAL_REQUIRED",
                "Hermes Run 等待审批；首期工作流不支持自动审批",
            )
            await self._finish_job(job)
            return
        if remote_status in {
            "queued",
            "running",
            "pending",
            "in_progress",
            "waiting",
            "",
        }:
            job.status = "queued"
            job.available_at = utcnow() + timedelta(
                seconds=settings.workflow_monitor_poll_seconds
            )
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utcnow()
            return
        if remote_status in {"succeeded", "success", "completed", "done"}:
            # A Manager-side cancellation revokes this Attempt before Hermes
            # necessarily observes its stop request.  A late successful poll
            # must therefore not re-materialize outputs, variables, or control
            # decisions after they were invalidated by ``request_cancel``.
            if run.cancel_requested_at is not None or node.status == "stop_requested":
                attempt.status = "cancelled"
                attempt.error_code = "RUN_CANCELLED"
                attempt.error_message = "工作流取消后忽略 Hermes 成功结果"
                attempt.finished_at = utcnow()
                attempt.updated_at = utcnow()
                await self._invalidate_attempt_artifacts(run, attempt)
                await self._cancel_node(run, scope, node, "工作流取消")
                await self._finish_job(job)
                return
            try:
                output_artifact = await self._materialize_system_artifact(
                    run=run,
                    node=node,
                    attempt=attempt,
                    name="node-output.json",
                    payload=_extract_remote_output(payload),
                    kind="system_output",
                )
            except ArtifactStoreError as exc:
                attempt.status = "failed"
                attempt.error_code = "NODE_OUTPUT_ARTIFACT_FAILED"
                attempt.error_message = str(exc)[:2048]
                attempt.finished_at = utcnow()
                await self._invalidate_attempt_artifacts(run, attempt)
                await self._fail_node(
                    run,
                    scope,
                    node,
                    "NODE_OUTPUT_ARTIFACT_FAILED",
                    "Hermes 输出无法物化为 node-output.json",
                )
                await self._finish_job(job)
                return
            attempt.status = "succeeded"
            attempt.finished_at = utcnow()
            await self._commit_attempt_dataflow(run=run, node=node, attempt=attempt)
            staged_cleanup = await invalidate_attempt_artifacts(
                self.session, attempt=attempt, include_available=False
            )
            if staged_cleanup.staged_bytes:
                run.budget = {
                    **run.budget,
                    "artifact_staged_bytes": max(
                        0,
                        int(run.budget.get("artifact_staged_bytes", 0))
                        - staged_cleanup.staged_bytes,
                    ),
                }
            await self._complete_node(
                run,
                scope,
                node,
                {"node_output": _artifact_metadata(output_artifact)},
            )
        elif remote_status in {"cancelled", "canceled", "stopped"}:
            attempt.status = "cancelled"
            attempt.finished_at = utcnow()
            await self._invalidate_attempt_artifacts(run, attempt)
            await self._cancel_node(run, scope, node, "Hermes Run 已停止")
        elif remote_status in {"failed", "error", "rejected", "expired"}:
            attempt.status = "failed"
            attempt.error_code = "HERMES_RUN_FAILED"
            attempt.error_message = _extract_remote_error(payload)
            attempt.finished_at = utcnow()
            await self._invalidate_attempt_artifacts(run, attempt)
            await self._fail_node(
                run, scope, node, "HERMES_RUN_FAILED", attempt.error_message
            )
        else:
            job.status = "queued"
            job.available_at = utcnow() + timedelta(
                seconds=settings.workflow_monitor_poll_seconds
            )
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utcnow()
            return
        await self._finish_job(job)

    async def release_monitor_after_error(self, *, monitor: HermesMonitor) -> None:
        run = await self._locked_run(monitor.workflow_run_id)
        job = await self._job(monitor.job_id)
        if not await self._ensure_run_dsl_v2(run):
            await self._finish_job(job)
            return
        if job.status == "running" and job.fencing_token == monitor.fencing_token:
            job.status = "queued"
            job.available_at = utcnow() + timedelta(
                seconds=settings.workflow_monitor_poll_seconds
            )
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utcnow()

    async def prepare_cancel(
        self, *, job: WorkflowJob, fencing_token: int
    ) -> HermesMonitor | None:
        if (
            job.fencing_token != fencing_token
            or job.status != "running"
            or job.attempt_id is None
        ):
            return None
        run = await self._locked_run(job.workflow_run_id)
        attempt = await self._attempt(job.attempt_id)
        node = await self._node_by_id(attempt.node_run_id)
        if (
            node.active_attempt_id != attempt.id
            or attempt.status != "dispatched"
            or node.status != "stop_requested"
            or attempt.external_run_id is None
        ):
            await self._finish_job(job)
            return None
        instance_id = attempt.executor_instance_id
        if not instance_id:
            node_plan = self._plan(await self._scope(node.scope_run_id))["nodes"][
                node.node_definition_id
            ]
            instance_id = str(node_plan["config"]["instance_id"])
        return HermesMonitor(
            job_id=job.id,
            fencing_token=fencing_token,
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            base_url=self._gateway_base_url(instance_id),
            api_key=settings.nineclaw_token,
            external_run_id=attempt.external_run_id,
        )

    async def persist_cancel_accepted(self, *, cancel: HermesMonitor) -> None:
        job = await self._job(cancel.job_id)
        if job.status == "running" and job.fencing_token == cancel.fencing_token:
            await self._finish_job(job)

    async def persist_cancel_unconfirmed(
        self, *, cancel: HermesMonitor, error: str
    ) -> None:
        run = await self._locked_run(cancel.workflow_run_id)
        job = await self._job(cancel.job_id)
        node = await self._node_by_id(cancel.node_run_id)
        attempt = await self._attempt(cancel.attempt_id)
        if job.status != "running" or job.fencing_token != cancel.fencing_token:
            return
        unsupported_v1_stop = (
            run.status == "failed"
            and run.attention_reason == "WORKFLOW_DSL_V1_UNSUPPORTED"
            and node.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
            and attempt.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
        )
        if (
            (
                run.status in {"succeeded", "failed", "cancelled"}
                and not unsupported_v1_stop
            )
            or node.active_attempt_id != attempt.id
            or node.status != "stop_requested"
            or attempt.status != "dispatched"
        ):
            await append_event(
                self.session,
                run=run,
                event_type="attempt.stop_result_ignored",
                data={"attempt_id": str(attempt.id)},
            )
            await self._finish_job(job)
            return
        node.status = "stop_unconfirmed"
        node.error_code = "STOP_UNCONFIRMED"
        node.error_message = error[:2048]
        node.updated_at = utcnow()
        attempt.status = "stop_unconfirmed"
        attempt.error_code = "STOP_UNCONFIRMED"
        attempt.error_message = error[:2048]
        attempt.updated_at = utcnow()
        await self._invalidate_attempt_artifacts(run, attempt)
        if not unsupported_v1_stop:
            run.status = "attention_required"
            run.attention_reason = error[:2048]
            run.updated_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="node.stop_unconfirmed",
            data={
                "node_run_id": str(node.id),
                "message": error,
                **(
                    {"code": "WORKFLOW_DSL_V1_UNSUPPORTED"}
                    if unsupported_v1_stop
                    else {}
                ),
            },
        )
        if not unsupported_v1_stop:
            await append_event(
                self.session,
                run=run,
                event_type="workflow.attention_required",
                data={"message": error},
            )
        await self._finish_job(job)

    async def request_cancel(
        self, *, run: WorkflowRun, requested_by: str | None
    ) -> None:
        run = await self._locked_run(run.id)
        if not await self._ensure_run_dsl_v2(run):
            # The cutover audit must commit even when this endpoint is the
            # first path that sees a persisted v1 Run.
            return
        if run.status in {"succeeded", "failed", "cancelled"}:
            raise WorkflowEngineError("工作流已终态，不能取消")
        run.cancel_requested_at = utcnow()
        run.cancel_requested_by = requested_by
        run.status = "cancel_requested"
        run.updated_at = utcnow()
        await append_event(
            self.session, run=run, event_type="workflow.cancel_requested", data={}
        )
        nodes = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run.id
                    )
                )
            ).all()
        )
        for node in nodes:
            scope = await self._scope(node.scope_run_id)
            if node.status in {"pending", "ready"}:
                await self._cancel_pending_node(run, scope, node, "工作流取消")
            elif node.status == "succeeded" and node.active_attempt_id is not None:
                attempt = await self._attempt(node.active_attempt_id)
                if attempt.status == "succeeded":
                    await self._invalidate_attempt_artifacts(run, attempt)
                    attempt.status = "cancelled"
                    attempt.error_code = "RUN_CANCELLED"
                    attempt.error_message = "工作流取消后撤销节点产物与变量"
                    attempt.updated_at = utcnow()
                    node.variable_state = _snapshot_variable_state(node.input_snapshot)
                    node.output = None
                    node.updated_at = utcnow()
            elif (
                node.status in {"dispatching", "running"}
                and node.active_attempt_id is not None
            ):
                attempt = await self._attempt(node.active_attempt_id)
                await self._invalidate_attempt_artifacts(run, attempt)
                if attempt.external_run_id:
                    node.status = "stop_requested"
                    await self._enqueue_job(
                        run=run,
                        scope_run_id=scope.id,
                        node_run_id=node.id,
                        attempt_id=attempt.id,
                        job_type="cancel_hermes",
                        dedupe_key=f"cancel:{attempt.id}",
                        payload={},
                    )
                else:
                    await self._mark_uncertain(
                        run, node, attempt, "取消时 Hermes 派发结果未知"
                    )

    async def resolve_uncertain_as_failed(
        self, *, run: WorkflowRun, node: WorkflowNodeRun, reason: str
    ) -> None:
        run = await self._locked_run(run.id)
        if not await self._run_uses_dsl_v2(run):
            raise WorkflowEngineError("WORKFLOW_DSL_V1_UNSUPPORTED")
        node = await self._node_by_id(node.id)
        if node.status not in ATTENTION_NODE_STATES:
            raise WorkflowEngineError("当前节点不需要人工处置")
        scope = await self._scope(node.scope_run_id)
        await self._fail_node(run, scope, node, "MANUAL_RESOLUTION", reason)
        await self._resolve_attention(run)

    async def retry_uncertain(self, *, run: WorkflowRun, node: WorkflowNodeRun) -> None:
        run = await self._locked_run(run.id)
        if not await self._run_uses_dsl_v2(run):
            raise WorkflowEngineError("WORKFLOW_DSL_V1_UNSUPPORTED")
        node = await self._node_by_id(node.id)
        if run.cancel_requested_at is not None:
            raise WorkflowEngineError("工作流已取消，禁止创建新 Attempt")
        if node.status not in ATTENTION_NODE_STATES:
            raise WorkflowEngineError("仅不确定节点可以在同一运行内重试")
        if node.active_attempt_id is not None:
            attempt = await self._attempt(node.active_attempt_id)
            attempt.status = "abandoned"
            attempt.updated_at = utcnow()
            await self._invalidate_attempt_artifacts(run, attempt)
        scope = await self._scope(node.scope_run_id)
        node.status = "ready"
        node.active_attempt_id = None
        node.updated_at = utcnow()
        await self._enqueue_dispatch(run, scope, node)
        await append_event(
            self.session,
            run=run,
            event_type="node.ready",
            data={"node_run_id": str(node.id), "manual_retry": True},
        )
        await self._resolve_attention(run)

    async def bind_external_run(
        self, *, run: WorkflowRun, node: WorkflowNodeRun, external_run_id: str
    ) -> None:
        run = await self._locked_run(run.id)
        if not await self._run_uses_dsl_v2(run):
            raise WorkflowEngineError("WORKFLOW_DSL_V1_UNSUPPORTED")
        node = await self._node_by_id(node.id)
        if node.status not in ATTENTION_NODE_STATES or node.active_attempt_id is None:
            raise WorkflowEngineError("当前节点不能绑定 Hermes Run")
        attempt = await self._attempt(node.active_attempt_id)
        scope = await self._scope(node.scope_run_id)
        node_plan = self._plan(scope)["nodes"][node.node_definition_id]
        instance_id = str(node_plan["config"]["instance_id"])
        duplicate = await self.session.scalar(
            select(WorkflowNodeAttempt.id).where(
                WorkflowNodeAttempt.tenant_id == run.tenant_id,
                WorkflowNodeAttempt.executor_instance_id == instance_id,
                WorkflowNodeAttempt.external_run_id == external_run_id,
                WorkflowNodeAttempt.id != attempt.id,
            )
        )
        if duplicate is not None:
            raise WorkflowEngineError("该 Hermes Run 已绑定到其他节点 Attempt")
        attempt.executor_instance_id = instance_id
        attempt.external_run_id = external_run_id
        attempt.status = "dispatched"
        attempt.updated_at = utcnow()
        cancellation_requested = run.cancel_requested_at is not None
        node.status = "stop_requested" if cancellation_requested else "running"
        node.updated_at = utcnow()
        await self._enqueue_job(
            run=run,
            scope_run_id=scope.id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            job_type="monitor_hermes",
            dedupe_key=f"monitor:{attempt.id}",
            payload={},
        )
        if cancellation_requested:
            await self._enqueue_job(
                run=run,
                scope_run_id=scope.id,
                node_run_id=node.id,
                attempt_id=attempt.id,
                job_type="cancel_hermes",
                dedupe_key=f"cancel:{attempt.id}",
                payload={},
            )
        await self._resolve_attention(run)

    async def _materialize_scope(
        self, *, run: WorkflowRun, scope: WorkflowScopeRun, plan: dict[str, Any]
    ) -> None:
        for node_id, node in plan["nodes"].items():
            self.session.add(
                WorkflowNodeRun(
                    tenant_id=run.tenant_id,
                    workflow_run_id=run.id,
                    scope_run_id=scope.id,
                    node_definition_id=node_id,
                    node_type=node["type"],
                )
            )
        for edge_id, edge in plan["edges"].items():
            self.session.add(
                WorkflowEdgeRun(
                    tenant_id=run.tenant_id,
                    workflow_run_id=run.id,
                    scope_run_id=scope.id,
                    edge_definition_id=edge_id,
                    source_node_id=edge["source_node_id"],
                    source_port=edge.get("source_port", "default"),
                    target_node_id=edge["target_node_id"],
                    target_port=edge.get("target_port", "default"),
                )
            )
        await self.session.flush()

    async def _prepare_hermes(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        node_plan: dict[str, Any],
        job: WorkflowJob,
        fencing_token: int,
        worker_id: str,
    ) -> HermesDispatch | None:
        config = node_plan["config"]
        instance_id = str(config["instance_id"])
        instance = await self.session.scalar(
            select(ServiceInstance).where(
                ServiceInstance.id == instance_id,
                ServiceInstance.tenant_id == run.tenant_id,
            )
        )
        if instance is None or instance.actual_state != "running":
            await self._fail_node(
                run,
                scope,
                node,
                "HERMES_INSTANCE_UNAVAILABLE",
                "Hermes 实例不存在或未运行",
            )
            await self._finish_job(job)
            return None
        execution_id = f"wf-{run.id}-{node.id}-{node.generation + 1}-{uuid4().hex[:8]}"
        try:
            workspace_token = workspace_token_for_execution(
                execution_id=execution_id,
                instance_id=str(instance.id),
            )
        except WorkspaceBridgeConfigurationError as exc:
            await self._fail_node(
                run,
                scope,
                node,
                "WORKSPACE_BRIDGE_UNAVAILABLE",
                str(exc),
            )
            await self._finish_job(job)
            return None
        if not await self._reserve_hermes_budget(run):
            await self._fail_node(
                run,
                scope,
                node,
                "BUDGET_EXCEEDED",
                "工作流 Hermes Run 额度已耗尽",
            )
            await self._finish_job(job)
            return None
        node.generation += 1
        attempt = WorkflowNodeAttempt(
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            node_run_id=node.id,
            generation=node.generation,
            execution_id=execution_id,
            status="dispatching",
            executor_instance_id=instance.id,
            lease_owner=worker_id,
            lease_expires_at=utcnow()
            + timedelta(seconds=settings.workflow_job_lease_seconds),
            fencing_token=fencing_token,
        )
        node.status = "dispatching"
        node.active_attempt_id = attempt.id
        node.updated_at = utcnow()
        self.session.add(attempt)
        self.session.add(node)
        await append_event(
            self.session,
            run=run,
            event_type="node.dispatching",
            data={"node_run_id": str(node.id), "node_id": node.node_definition_id},
        )
        messages = _build_hermes_messages(config, node.input_snapshot or {})
        controls = await self._prepare_control_decisions(
            run=run,
            scope=scope,
            node=node,
            attempt=attempt,
        )
        return HermesDispatch(
            job_id=job.id,
            fencing_token=fencing_token,
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            base_url=self._gateway_base_url(instance.id),
            api_key=settings.nineclaw_token,
            model=str(config.get("model") or "hermes-agent"),
            messages=messages,
            instructions=_build_workspace_instructions(
                attempt.execution_id,
                workspace_token,
                controls,
            ),
            session_id=attempt.execution_id,
            extra={
                key: value
                for key, value in config.items()
                if key in {"temperature", "max_tokens"}
            },
        )

    async def _execute_local_node(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        node_plan: dict[str, Any],
    ) -> None:
        if node.node_type == "start":
            await self._complete_node(
                run,
                scope,
                node,
                {
                    "artifact_count": len(
                        (node.input_snapshot or {}).get("artifacts", [])
                    )
                },
            )
            return
        if node.node_type == "end":
            await self._complete_node(
                run,
                scope,
                node,
                {
                    "artifact_count": len(
                        (node.input_snapshot or {}).get("artifacts", [])
                    )
                },
            )
            return
        if node.node_type == "condition":
            try:
                config = node_plan["config"]
                if config.get("mode") == "agent":
                    port = await self._agent_condition_port(node)
                else:
                    port = _select_formula_condition_port(
                        config, _formula_context(node.input_snapshot or {})
                    )
            except (ExpressionError, WorkflowEngineError) as exc:
                await self._fail_node(run, scope, node, "CONDITION_ERROR", str(exc))
                return
            await self._complete_node(
                run, scope, node, {"selected_port": port}, selected_ports={port}
            )
            return
        if node.node_type == "loop":
            await self._start_loop(run, scope, node, node_plan)
            return
        await self._fail_node(
            run, scope, node, "UNSUPPORTED_NODE", f"不支持节点类型：{node.node_type}"
        )

    async def _start_loop(
        self,
        run: WorkflowRun,
        parent_scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        node_plan: dict[str, Any],
    ) -> None:
        config = node_plan["config"]
        body_plan = node_plan.get("body_plan")
        if not isinstance(body_plan, dict):
            await self._fail_node(
                run, parent_scope, node, "LOOP_PLAN_MISSING", "Loop Body 编译计划缺失"
            )
            return
        node.status = "running"
        node.updated_at = utcnow()
        snapshot = node.input_snapshot or {}
        await self._create_loop_iteration(
            run=run,
            parent_scope=parent_scope,
            parent_node=node,
            body_plan=body_plan,
            iteration=0,
            inherited_artifact_ids=list(snapshot.get("artifact_ids") or []),
            inherited_variable_state=dict(snapshot.get("variable_state") or {}),
        )
        await append_event(
            self.session,
            run=run,
            event_type="loop.iteration.started",
            data={"node_run_id": str(node.id), "iteration": 0},
        )

    async def _create_loop_iteration(
        self,
        *,
        run: WorkflowRun,
        parent_scope: WorkflowScopeRun,
        parent_node: WorkflowNodeRun,
        body_plan: dict[str, Any],
        iteration: int,
        inherited_artifact_ids: list[str],
        inherited_variable_state: dict[str, Any],
    ) -> WorkflowScopeRun:
        scope = WorkflowScopeRun(
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            parent_scope_run_id=parent_scope.id,
            parent_node_run_id=parent_node.id,
            kind="loop_iteration",
            iteration_index=iteration,
            state={
                "plan": body_plan,
                "inherited_artifact_ids": inherited_artifact_ids,
                "inherited_variable_state": inherited_variable_state,
            },
        )
        self.session.add(scope)
        await self.session.flush()
        await self._materialize_scope(run=run, scope=scope, plan=body_plan)
        start = await self._node(run.id, scope.id, str(body_plan["root_node_id"]))
        await self._ready_node(
            run=run,
            scope=scope,
            node=start,
            input_snapshot=await self._resolve_input_snapshot(run, scope, start),
        )
        return scope

    async def _complete_node(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        output: dict[str, Any],
        *,
        selected_ports: set[str] | None = None,
    ) -> None:
        if is_node_terminal(node.status):
            return
        node.status = "succeeded"
        node.output = output
        if not node.variable_state:
            node.variable_state = _snapshot_variable_state(node.input_snapshot)
        node.error_code = None
        node.error_message = None
        node.updated_at = utcnow()
        node.finished_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="node.succeeded",
            data={"node_run_id": str(node.id), "node_id": node.node_definition_id},
        )
        await self._resolve_outgoing(
            run, scope, node, selected_ports=selected_ports, terminal="succeeded"
        )
        await self._maybe_finalize_scope(run, scope)

    async def _fail_node(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        code: str,
        message: str,
    ) -> None:
        if is_node_terminal(node.status):
            return
        node.status = "failed"
        node.error_code = code
        node.error_message = message[:2048]
        node.updated_at = utcnow()
        node.finished_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="node.failed",
            data={
                "node_run_id": str(node.id),
                "node_id": node.node_definition_id,
                "code": code,
                "message": message,
            },
        )
        await self._resolve_outgoing(
            run, scope, node, selected_ports=None, terminal="failed"
        )
        await self._maybe_finalize_scope(run, scope)

    async def _cancel_node(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        message: str,
    ) -> None:
        if is_node_terminal(node.status):
            return
        node.status = "cancelled"
        node.error_message = message[:2048]
        node.updated_at = utcnow()
        node.finished_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="node.cancelled",
            data={"node_run_id": str(node.id), "node_id": node.node_definition_id},
        )
        await self._resolve_outgoing(
            run, scope, node, selected_ports=None, terminal="cancelled"
        )
        await self._maybe_finalize_scope(run, scope)

    async def _cancel_pending_node(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        message: str,
    ) -> None:
        await self._cancel_node(run, scope, node, message)

    async def _mark_uncertain(
        self,
        run: WorkflowRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
        message: str,
    ) -> None:
        await self._mark_attention(
            run, node, attempt, "HERMES_DISPATCH_UNKNOWN", message
        )

    async def _mark_attention(
        self,
        run: WorkflowRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
        code: str,
        message: str,
    ) -> None:
        attempt.status = "uncertain"
        attempt.error_code = code
        attempt.error_message = message[:2048]
        attempt.updated_at = utcnow()
        await self._invalidate_attempt_artifacts(run, attempt)
        node.status = "uncertain"
        node.error_code = code
        node.error_message = message[:2048]
        node.updated_at = utcnow()
        run.status = "attention_required"
        run.attention_reason = message[:2048]
        run.updated_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="node.uncertain",
            data={"node_run_id": str(node.id), "message": message},
        )
        await append_event(
            self.session,
            run=run,
            event_type="workflow.attention_required",
            data={"message": message},
        )

    async def _resolve_outgoing(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        *,
        selected_ports: set[str] | None,
        terminal: str,
    ) -> None:
        plan = self._plan(scope)
        edge_ids = plan["outgoing_edge_ids"].get(node.node_definition_id, [])
        affected_targets: set[str] = set()
        for edge_id in edge_ids:
            edge_plan = plan["edges"][edge_id]
            edge_run = await self._edge(run.id, scope.id, edge_id)
            if edge_run.status != EDGE_PENDING:
                continue
            if terminal == "succeeded":
                if node.node_type == "condition":
                    edge_run.status = (
                        EDGE_TAKEN
                        if edge_plan.get("source_port", "default")
                        in (selected_ports or set())
                        else EDGE_NOT_SELECTED
                    )
                else:
                    edge_run.status = EDGE_TAKEN
            elif terminal == "skipped":
                edge_run.status = EDGE_NOT_SELECTED
            else:
                edge_run.status = EDGE_BLOCKED
            edge_run.resolved_at = utcnow()
            affected_targets.add(edge_run.target_node_id)
        # The scheduler deliberately uses sessions with ``autoflush=False``.
        # Downstream snapshot queries filter by edge/Attempt status, so make
        # this transition visible before resolving every affected target.
        await self.session.flush()
        for target_id in sorted(affected_targets):
            await self._advance_target(run, scope, target_id)

    async def _advance_target(
        self, run: WorkflowRun, scope: WorkflowScopeRun, target_id: str
    ) -> None:
        node = await self._node(run.id, scope.id, target_id)
        if node.status != "pending":
            return
        edges = list(
            (
                await self.session.scalars(
                    select(WorkflowEdgeRun).where(
                        WorkflowEdgeRun.workflow_run_id == run.id,
                        WorkflowEdgeRun.scope_run_id == scope.id,
                        WorkflowEdgeRun.target_node_id == target_id,
                    )
                )
            ).all()
        )
        statuses = {edge.status for edge in edges}
        if EDGE_PENDING in statuses:
            return
        if EDGE_BLOCKED in statuses:
            node.status = "blocked"
            node.updated_at = utcnow()
            node.finished_at = utcnow()
            await append_event(
                self.session,
                run=run,
                event_type="node.blocked",
                data={"node_run_id": str(node.id), "node_id": target_id},
            )
            await self._resolve_outgoing(
                run, scope, node, selected_ports=None, terminal="blocked"
            )
            return
        if EDGE_TAKEN not in statuses:
            node.status = "skipped"
            node.updated_at = utcnow()
            node.finished_at = utcnow()
            await append_event(
                self.session,
                run=run,
                event_type="node.skipped",
                data={"node_run_id": str(node.id), "node_id": target_id},
            )
            await self._resolve_outgoing(
                run, scope, node, selected_ports=None, terminal="skipped"
            )
            return
        try:
            snapshot = await self._resolve_input_snapshot(run, scope, node)
        except WorkflowVariableConflictError as exc:
            await self._fail_node(run, scope, node, "VARIABLE_CONFLICT", str(exc))
            return
        except ExpressionError as exc:
            await self._fail_node(run, scope, node, "INPUT_SNAPSHOT_ERROR", str(exc))
            return
        await self._ready_node(run=run, scope=scope, node=node, input_snapshot=snapshot)

    async def _ready_node(
        self,
        *,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        input_snapshot: dict[str, Any],
    ) -> None:
        if node.status not in {"pending", "ready"}:
            return
        node.input_snapshot = input_snapshot
        node.status = "ready"
        node.updated_at = utcnow()
        await self._enqueue_dispatch(run, scope, node)
        await append_event(
            self.session,
            run=run,
            event_type="node.ready",
            data={"node_run_id": str(node.id), "node_id": node.node_definition_id},
        )

    async def _enqueue_dispatch(
        self, run: WorkflowRun, scope: WorkflowScopeRun, node: WorkflowNodeRun
    ) -> None:
        await self._enqueue_job(
            run=run,
            scope_run_id=scope.id,
            node_run_id=node.id,
            attempt_id=None,
            job_type="dispatch_node",
            dedupe_key=f"dispatch:{node.id}:{node.generation + 1}",
            payload={},
        )

    async def _enqueue_job(
        self,
        *,
        run: WorkflowRun,
        scope_run_id: UUID | None,
        node_run_id: UUID | None,
        attempt_id: UUID | None,
        job_type: str,
        dedupe_key: str,
        payload: dict[str, Any],
    ) -> WorkflowJob:
        existing = await self.session.scalar(
            select(WorkflowJob).where(
                WorkflowJob.tenant_id == run.tenant_id,
                WorkflowJob.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            return existing
        job = WorkflowJob(
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            scope_run_id=scope_run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            job_type=job_type,
            dedupe_key=dedupe_key,
            payload=payload,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def _maybe_finalize_scope(
        self, run: WorkflowRun, scope: WorkflowScopeRun
    ) -> None:
        nodes = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run.id,
                        WorkflowNodeRun.scope_run_id == scope.id,
                    )
                )
            ).all()
        )
        if not nodes or any(not is_node_terminal(node.status) for node in nodes):
            return
        if scope.status in {"succeeded", "failed", "cancelled"}:
            return
        if any(node.status in {"failed", "blocked"} for node in nodes):
            scope.status = "failed"
            scope.finished_at = utcnow()
            if scope.parent_node_run_id is None:
                await self._finish_root_run(run, scope, nodes, failed=True)
            else:
                parent = await self._node_by_id(scope.parent_node_run_id)
                parent_scope = (
                    await self._scope(scope.parent_scope_run_id)
                    if scope.parent_scope_run_id
                    else scope
                )
                await self._fail_node(
                    run, parent_scope, parent, "LOOP_BODY_FAILED", "Loop Body 执行失败"
                )
            return
        if any(node.status == "cancelled" for node in nodes):
            scope.status = "cancelled"
            scope.finished_at = utcnow()
            if scope.parent_node_run_id is None:
                await self._finish_root_run(
                    run, scope, nodes, failed=False, cancelled=True
                )
            else:
                parent = await self._node_by_id(scope.parent_node_run_id)
                parent_scope = await self._scope(scope.parent_scope_run_id)
                await self._cancel_node(run, parent_scope, parent, "Loop Body 已取消")
            return
        scope.status = "succeeded"
        scope.finished_at = utcnow()
        if scope.parent_node_run_id is None:
            await self._finish_root_run(run, scope, nodes, failed=False)
        else:
            await self._complete_loop_iteration(run, scope, nodes)

    async def _complete_loop_iteration(
        self, run: WorkflowRun, scope: WorkflowScopeRun, nodes: list[WorkflowNodeRun]
    ) -> None:
        parent = await self._node_by_id(scope.parent_node_run_id)  # type: ignore[arg-type]
        parent_scope = await self._scope(scope.parent_scope_run_id)  # type: ignore[arg-type]
        parent_plan = self._plan(parent_scope)["nodes"][parent.node_definition_id]
        config = parent_plan["config"]
        end_nodes = [node for node in nodes if node.node_type == "end"]
        end_node = end_nodes[0] if end_nodes else None
        iteration = int(scope.iteration_index or 0)
        try:
            termination = config["termination"]
            if termination["mode"] == "agent":
                should_continue = await self._agent_loop_continue(
                    scope=scope,
                    parent=parent,
                )
            else:
                # ``termination.expression`` answers whether this completed
                # iteration is terminal.  It intentionally has the opposite
                # polarity of the Agent tool's explicit ``should_continue``.
                should_continue = not bool(
                    evaluate(
                        termination["expression"],
                        _formula_context(
                            end_node.input_snapshot if end_node is not None else {}
                        ),
                    )
                )
        except (ExpressionError, WorkflowEngineError) as exc:
            await self._fail_node(
                run, parent_scope, parent, "LOOP_TERMINATION_ERROR", str(exc)
            )
            return
        max_iterations = int(config["limits"]["max_iterations"])
        await append_event(
            self.session,
            run=run,
            event_type="loop.iteration.completed",
            data={
                "node_run_id": str(parent.id),
                "iteration": iteration,
                "continue": should_continue,
            },
        )
        if should_continue:
            if iteration + 1 >= max_iterations:
                await self._fail_node(
                    run,
                    parent_scope,
                    parent,
                    "LOOP_LIMIT_EXCEEDED",
                    "Loop 达到最大迭代次数",
                )
                return
            await self._create_loop_iteration(
                run=run,
                parent_scope=parent_scope,
                parent_node=parent,
                body_plan=parent_plan["body_plan"],
                iteration=iteration + 1,
                inherited_artifact_ids=await self._scope_artifact_ids(scope),
                inherited_variable_state=(
                    dict(end_node.variable_state) if end_node is not None else {}
                ),
            )
            await append_event(
                self.session,
                run=run,
                event_type="loop.iteration.started",
                data={"node_run_id": str(parent.id), "iteration": iteration + 1},
            )
            return
        parent.variable_state = (
            dict(end_node.variable_state) if end_node is not None else {}
        )
        await self._complete_node(
            run,
            parent_scope,
            parent,
            {
                "iteration_count": iteration + 1,
                "artifact_count": len(await self._scope_artifact_ids(scope)),
            },
        )

    async def _finish_root_run(
        self,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        nodes: list[WorkflowNodeRun],
        *,
        failed: bool,
        cancelled: bool = False,
    ) -> None:
        run = await self._locked_run(run.id)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return
        if any(node.status in ATTENTION_NODE_STATES for node in nodes):
            return
        if cancelled or run.cancel_requested_at is not None:
            run.status = "cancelled"
            run.output = {**(run.output or {}), "final_artifact_ids": []}
            event_type = "workflow.cancelled"
            data: dict[str, Any] = {}
        elif failed:
            run.status = "failed"
            run.output = {**(run.output or {}), "final_artifact_ids": []}
            event_type = "workflow.failed"
            data = {}
        else:
            if run.run_kind == "node_debug":
                debug_node = next(
                    (
                        node
                        for node in nodes
                        if node.node_definition_id == run.debug_node_id
                    ),
                    None,
                )
                run.output = {
                    "node_output": (
                        debug_node.output if debug_node is not None else None
                    ),
                    "final_artifact_ids": [],
                }
            else:
                ends = [node.output for node in nodes if node.node_type == "end"]
                try:
                    final_artifact_ids = (
                        await self._collect_final_artifact_ids(run=run, nodes=nodes)
                        if run.run_kind == "workflow"
                        else []
                    )
                except WorkflowFinalArtifactValidationError:
                    scope.status = "failed"
                    scope.finished_at = utcnow()
                    run.status = "failed"
                    run.output = {
                        "end_outputs": ends,
                        "final_artifact_ids": [],
                    }
                    event_type = "workflow.failed"
                    data = {"code": "FINAL_ARTIFACT_VALIDATION_FAILED"}
                else:
                    run.status = "succeeded"
                    run.output = {
                        "end_outputs": ends,
                        "final_artifact_ids": final_artifact_ids,
                    }
                    event_type = "workflow.succeeded"
                    data = {"output": run.output}
                run.finished_at = utcnow()
                run.updated_at = utcnow()
                await append_event(
                    self.session, run=run, event_type=event_type, data=data
                )
                return
            run.status = "succeeded"
            event_type = "workflow.succeeded"
            data = {"output": run.output}
        run.finished_at = utcnow()
        run.updated_at = utcnow()
        await append_event(self.session, run=run, event_type=event_type, data=data)

    async def _collect_final_artifact_ids(
        self, *, run: WorkflowRun, nodes: list[WorkflowNodeRun]
    ) -> list[str]:
        """Collect non-system Artifacts from the selected closure of every End."""
        if not nodes:
            return []
        scope = await self._scope(nodes[0].scope_run_id)
        ancestors: set[str] = set()
        for end in nodes:
            if end.node_type == "end" and end.status == "succeeded":
                ancestors |= await self._selected_upstream_node_ids(
                    run=run, scope=scope, node=end
                )
        if not ancestors:
            return []
        source_nodes = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run.id,
                        WorkflowNodeRun.scope_run_id == scope.id,
                        WorkflowNodeRun.node_definition_id.in_(ancestors),
                        WorkflowNodeRun.status == "succeeded",
                    )
                )
            ).all()
        )
        attempt_ids = {
            item.active_attempt_id
            for item in source_nodes
            if item.active_attempt_id is not None
        }
        loop_nodes = [item for item in source_nodes if item.node_type == "loop"]
        if loop_nodes:
            loop_scope_ids = list(
                (
                    await self.session.scalars(
                        select(WorkflowScopeRun.id).where(
                            WorkflowScopeRun.workflow_run_id == run.id,
                            WorkflowScopeRun.parent_node_run_id.in_(
                                [item.id for item in loop_nodes]
                            ),
                            WorkflowScopeRun.status == "succeeded",
                        )
                    )
                ).all()
            )
            if loop_scope_ids:
                attempt_ids |= {
                    item
                    for item in (
                        await self.session.scalars(
                            select(WorkflowNodeRun.active_attempt_id).where(
                                WorkflowNodeRun.workflow_run_id == run.id,
                                WorkflowNodeRun.scope_run_id.in_(loop_scope_ids),
                                WorkflowNodeRun.active_attempt_id.is_not(None),
                            )
                        )
                    ).all()
                    if item is not None
                }
        if not attempt_ids:
            return []
        artifacts = list(
            (
                await self.session.scalars(
                    select(WorkflowArtifact)
                    .join(
                        WorkflowNodeAttempt,
                        WorkflowArtifact.created_by_attempt_id
                        == WorkflowNodeAttempt.id,
                    )
                    .where(
                        WorkflowArtifact.tenant_id == run.tenant_id,
                        WorkflowArtifact.workflow_run_id == run.id,
                        WorkflowArtifact.created_by_attempt_id.in_(attempt_ids),
                        WorkflowNodeAttempt.status == "succeeded",
                        WorkflowArtifact.status == "available",
                        WorkflowArtifact.kind.not_in(("system_input", "system_output")),
                    )
                    .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                )
            ).all()
        )
        return [str(artifact.id) for artifact in artifacts]

    async def _resolve_attention(self, run: WorkflowRun) -> None:
        if run.status != "attention_required":
            return
        count = await self.session.scalar(
            select(WorkflowNodeRun)
            .where(
                WorkflowNodeRun.workflow_run_id == run.id,
                WorkflowNodeRun.status.in_(ATTENTION_NODE_STATES),
            )
            .limit(1)
        )
        if count is None:
            run.status = (
                "cancel_requested" if run.cancel_requested_at is not None else "running"
            )
            run.attention_reason = None
            run.updated_at = utcnow()
            await append_event(
                self.session, run=run, event_type="workflow.attention_resolved", data={}
            )

    async def _consume_node_budget(self, run: WorkflowRun) -> bool:
        current = int(run.budget.get("node_executions", 0))
        maximum = int(run.budget.get("max_node_executions", 0))
        if maximum and current >= maximum:
            return False
        run.budget = {**run.budget, "node_executions": current + 1}
        run.updated_at = utcnow()
        return True

    async def _reserve_hermes_budget(self, run: WorkflowRun) -> bool:
        maximum = int(run.budget.get("max_hermes_runs", 0))
        completed = int(run.budget.get("hermes_runs", 0))
        in_flight = int(run.budget.get("hermes_in_flight", 0))
        if maximum and completed + in_flight >= maximum:
            return False
        run.budget = {**run.budget, "hermes_in_flight": in_flight + 1}
        run.updated_at = utcnow()
        return True

    async def _settle_hermes_reservation(
        self, run: WorkflowRun, *, created_or_unknown: bool
    ) -> None:
        in_flight = max(0, int(run.budget.get("hermes_in_flight", 0)) - 1)
        budget = {**run.budget, "hermes_in_flight": in_flight}
        if created_or_unknown:
            budget["hermes_runs"] = int(budget.get("hermes_runs", 0)) + 1
        run.budget = budget
        run.updated_at = utcnow()

    async def _resolve_input_snapshot(
        self, run: WorkflowRun, scope: WorkflowScopeRun, node: WorkflowNodeRun
    ) -> dict[str, Any]:
        artifacts = await self._snapshot_artifacts(run=run, scope=scope, node=node)
        variable_state = await self._resolve_variable_state(
            run=run, scope=scope, node=node
        )
        return {
            "artifact_ids": [str(artifact.id) for artifact in artifacts],
            "artifacts": [_artifact_metadata(artifact) for artifact in artifacts],
            "variables": {
                name: entry["value"]
                for name, entry in sorted(variable_state.items())
                if isinstance(entry, dict) and "value" in entry
            },
            "variable_state": variable_state,
            "system": {
                "artifact_count": len(artifacts),
                "scope_kind": scope.kind,
                "iteration_index": scope.iteration_index,
            },
        }

    async def _snapshot_artifacts(
        self, *, run: WorkflowRun, scope: WorkflowScopeRun, node: WorkflowNodeRun
    ) -> list[WorkflowArtifact]:
        """Freeze only physical workspace Artifacts selected by the DAG path."""
        # A source node can become terminal in this transaction.  Its
        # successful Attempt and selected edges must be queryable before the
        # snapshot freezes authorization for this target node.
        await self.session.flush()
        allowed_ids = _uuid_list(scope.state.get("inherited_artifact_ids"))
        ancestors = await self._selected_upstream_node_ids(
            run=run, scope=scope, node=node
        )
        source_nodes = (
            list(
                (
                    await self.session.scalars(
                        select(WorkflowNodeRun).where(
                            WorkflowNodeRun.workflow_run_id == run.id,
                            WorkflowNodeRun.scope_run_id == scope.id,
                            WorkflowNodeRun.node_definition_id.in_(ancestors),
                            WorkflowNodeRun.status == "succeeded",
                        )
                    )
                ).all()
            )
            if ancestors
            else []
        )
        attempt_ids = {
            item.active_attempt_id
            for item in source_nodes
            if item.active_attempt_id is not None
        }
        if attempt_ids:
            succeeded_attempt_ids = set(
                (
                    await self.session.scalars(
                        select(WorkflowNodeAttempt.id).where(
                            WorkflowNodeAttempt.id.in_(attempt_ids),
                            WorkflowNodeAttempt.status == "succeeded",
                        )
                    )
                ).all()
            )
            allowed_ids.extend(
                list(
                    (
                        await self.session.scalars(
                            select(WorkflowArtifact.id).where(
                                WorkflowArtifact.created_by_attempt_id.in_(
                                    succeeded_attempt_ids
                                ),
                                WorkflowArtifact.status == "available",
                            )
                        )
                    ).all()
                )
            )
        loop_nodes = [item for item in source_nodes if item.node_type == "loop"]
        if loop_nodes:
            loop_scope_ids = list(
                (
                    await self.session.scalars(
                        select(WorkflowScopeRun.id).where(
                            WorkflowScopeRun.workflow_run_id == run.id,
                            WorkflowScopeRun.parent_node_run_id.in_(
                                [item.id for item in loop_nodes]
                            ),
                            WorkflowScopeRun.status == "succeeded",
                        )
                    )
                ).all()
            )
            if loop_scope_ids:
                loop_attempt_ids = set(
                    (
                        await self.session.scalars(
                            select(WorkflowNodeRun.active_attempt_id).where(
                                WorkflowNodeRun.workflow_run_id == run.id,
                                WorkflowNodeRun.scope_run_id.in_(loop_scope_ids),
                                WorkflowNodeRun.active_attempt_id.is_not(None),
                            )
                        )
                    ).all()
                )
                if loop_attempt_ids:
                    succeeded_loop_attempt_ids = set(
                        (
                            await self.session.scalars(
                                select(WorkflowNodeAttempt.id).where(
                                    WorkflowNodeAttempt.id.in_(loop_attempt_ids),
                                    WorkflowNodeAttempt.status == "succeeded",
                                )
                            )
                        ).all()
                    )
                    allowed_ids.extend(
                        list(
                            (
                                await self.session.scalars(
                                    select(WorkflowArtifact.id).where(
                                        WorkflowArtifact.created_by_attempt_id.in_(
                                            succeeded_loop_attempt_ids
                                        ),
                                        WorkflowArtifact.status == "available",
                                    )
                                )
                            ).all()
                        )
                    )
        if not allowed_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    select(WorkflowArtifact)
                    .where(
                        WorkflowArtifact.id.in_(set(allowed_ids)),
                        WorkflowArtifact.tenant_id == run.tenant_id,
                        WorkflowArtifact.workflow_run_id == run.id,
                        WorkflowArtifact.status == "available",
                    )
                    .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                )
            ).all()
        )

    async def _scope_artifact_ids(self, scope: WorkflowScopeRun) -> list[str]:
        """Carry the prior loop iteration workspace into the next iteration."""
        await self.session.flush()
        node_attempt_ids = {
            item.active_attempt_id
            for item in (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == scope.workflow_run_id,
                        WorkflowNodeRun.scope_run_id == scope.id,
                    )
                )
            ).all()
            if item.active_attempt_id is not None
        }
        artifact_ids = _uuid_list(scope.state.get("inherited_artifact_ids"))
        if node_attempt_ids:
            artifact_ids.extend(
                list(
                    (
                        await self.session.scalars(
                            select(WorkflowArtifact.id).where(
                                WorkflowArtifact.created_by_attempt_id.in_(
                                    node_attempt_ids
                                ),
                                WorkflowArtifact.status == "available",
                            )
                        )
                    ).all()
                )
            )
        return [str(value) for value in dict.fromkeys(artifact_ids)]

    async def _selected_upstream_node_ids(
        self, *, run: WorkflowRun, scope: WorkflowScopeRun, node: WorkflowNodeRun
    ) -> set[str]:
        selected: set[str] = set()
        pending = [node.node_definition_id]
        while pending:
            target_id = pending.pop()
            sources = list(
                (
                    await self.session.scalars(
                        select(WorkflowEdgeRun.source_node_id).where(
                            WorkflowEdgeRun.workflow_run_id == run.id,
                            WorkflowEdgeRun.scope_run_id == scope.id,
                            WorkflowEdgeRun.target_node_id == target_id,
                            WorkflowEdgeRun.status == EDGE_TAKEN,
                        )
                    )
                ).all()
            )
            for source_id in sources:
                if source_id not in selected:
                    selected.add(source_id)
                    pending.append(source_id)
        return selected

    async def _resolve_variable_state(
        self, *, run: WorkflowRun, scope: WorkflowScopeRun, node: WorkflowNodeRun
    ) -> dict[str, dict[str, Any]]:
        inherited_state = _snapshot_variable_state(scope.state)
        source_ids = list(
            (
                await self.session.scalars(
                    select(WorkflowEdgeRun.source_node_id).where(
                        WorkflowEdgeRun.workflow_run_id == run.id,
                        WorkflowEdgeRun.scope_run_id == scope.id,
                        WorkflowEdgeRun.target_node_id == node.node_definition_id,
                        WorkflowEdgeRun.status == EDGE_TAKEN,
                    )
                )
            ).all()
        )
        if not source_ids:
            return inherited_state
        source_nodes = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run.id,
                        WorkflowNodeRun.scope_run_id == scope.id,
                        WorkflowNodeRun.node_definition_id.in_(source_ids),
                    )
                )
            ).all()
        )
        source_state = await self._merge_variable_states(
            scope=scope,
            source_states={
                item.node_definition_id: dict(item.variable_state or {})
                for item in source_nodes
            },
        )
        # Every selected direct upstream node was derived from the scope's
        # inherited state.  Its value therefore has a causal edge over that
        # baseline, including when the source belongs to a later Loop scope.
        # Only sibling upstream states are an implicit merge and can conflict.
        return {**inherited_state, **source_state}

    async def _merge_variable_states(
        self,
        *,
        scope: WorkflowScopeRun,
        source_states: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Merge the states of direct selected predecessors only.

        A direct predecessor that can reach another direct predecessor is
        causally older and its complete state is already represented by the
        latter.  The remaining predecessors are concurrent branches.  Their
        full states must agree for every shared variable, including a value
        merely inherited from a common ancestor.
        """

        source_ids = sorted(source_states)
        if len(source_ids) < 2:
            states = list(source_states.values())
        else:
            edges = list(
                (
                    await self.session.execute(
                        select(
                            WorkflowEdgeRun.source_node_id,
                            WorkflowEdgeRun.target_node_id,
                        ).where(
                            WorkflowEdgeRun.workflow_run_id == scope.workflow_run_id,
                            WorkflowEdgeRun.scope_run_id == scope.id,
                            WorkflowEdgeRun.status == EDGE_TAKEN,
                        )
                    )
                ).all()
            )
            adjacency: dict[str, set[str]] = {}
            for source_id, target_id in edges:
                adjacency.setdefault(source_id, set()).add(target_id)

            def precedes(source_id: str, target_id: str) -> bool:
                pending = list(adjacency.get(source_id, ()))
                visited: set[str] = set()
                while pending:
                    current = pending.pop()
                    if current in visited:
                        continue
                    if current == target_id:
                        return True
                    visited.add(current)
                    pending.extend(adjacency.get(current, ()))
                return False

            active_source_ids = [
                source_id
                for source_id in source_ids
                if not any(
                    other_id != source_id and precedes(source_id, other_id)
                    for other_id in source_ids
                )
            ]
            states = [source_states[source_id] for source_id in active_source_ids]
        candidates: dict[str, list[dict[str, Any]]] = {}
        for state in states:
            for name, entry in state.items():
                if isinstance(entry, dict) and "value" in entry:
                    candidates.setdefault(name, []).append(dict(entry))
        merged: dict[str, dict[str, Any]] = {}
        for name, entries in candidates.items():
            values = {
                json.dumps(item["value"], ensure_ascii=False, sort_keys=True)
                for item in entries
            }
            if len(values) > 1:
                raise WorkflowVariableConflictError(f"变量 '{name}' 在并行路径上值冲突")
            if entries:
                merged[name] = entries[0]
        return merged

    async def _commit_attempt_dataflow(
        self,
        *,
        run: WorkflowRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
    ) -> None:
        variable_state = _snapshot_variable_state(node.input_snapshot)
        writes = list(
            (
                await self.session.scalars(
                    select(WorkflowVariableWrite)
                    .where(
                        WorkflowVariableWrite.attempt_id == attempt.id,
                        WorkflowVariableWrite.status == "staged",
                    )
                    .with_for_update()
                )
            ).all()
        )
        for write in writes:
            write.status = "committed"
            write.committed_at = utcnow()
            variable_state[write.name] = {
                "value": write.value,
                "origin_scope_run_id": str(node.scope_run_id),
                "origin_node_run_id": str(node.id),
                "origin_node_definition_id": node.node_definition_id,
                "origin_attempt_id": str(attempt.id),
            }
        node.variable_state = variable_state
        decisions = list(
            (
                await self.session.scalars(
                    select(WorkflowControlDecision)
                    .where(
                        WorkflowControlDecision.attempt_id == attempt.id,
                        WorkflowControlDecision.status.in_(("pending", "submitted")),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for decision in decisions:
            decision.status = "committed"
            decision.committed_at = utcnow()

    async def _prepare_control_decisions(
        self,
        *,
        run: WorkflowRun,
        scope: WorkflowScopeRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
    ) -> list[dict[str, Any]]:
        controls: list[dict[str, Any]] = []
        plan = self._plan(scope)
        for edge_id in plan["outgoing_edge_ids"].get(node.node_definition_id, []):
            edge = plan["edges"][edge_id]
            target_plan = plan["nodes"].get(edge["target_node_id"])
            if (
                not isinstance(target_plan, dict)
                or target_plan.get("type") != "condition"
                or target_plan.get("config", {}).get("mode") != "agent"
            ):
                continue
            target = await self._node(run.id, scope.id, edge["target_node_id"])
            ports = list(target_plan["config"].get("ports") or [])
            token = uuid4().hex
            self.session.add(
                WorkflowControlDecision(
                    tenant_id=run.tenant_id,
                    workflow_run_id=run.id,
                    scope_run_id=scope.id,
                    attempt_id=attempt.id,
                    target_node_run_id=target.id,
                    kind="condition",
                    token=token,
                    allowed_ports=ports,
                )
            )
            controls.append({"kind": "condition", "token": token, "ports": ports})
        if scope.parent_node_run_id is not None:
            parent = await self._node_by_id(scope.parent_node_run_id)
            parent_scope = await self._scope(scope.parent_scope_run_id)
            parent_plan = self._plan(parent_scope)["nodes"].get(
                parent.node_definition_id
            )
            termination = (
                parent_plan.get("config", {}).get("termination", {})
                if isinstance(parent_plan, dict)
                else {}
            )
            if (
                termination.get("mode") == "agent"
                and termination.get("source_node_id") == node.node_definition_id
            ):
                token = uuid4().hex
                self.session.add(
                    WorkflowControlDecision(
                        tenant_id=run.tenant_id,
                        workflow_run_id=run.id,
                        scope_run_id=scope.id,
                        attempt_id=attempt.id,
                        target_node_run_id=parent.id,
                        kind="loop",
                        token=token,
                        allowed_ports=["continue", "stop"],
                    )
                )
                controls.append({"kind": "loop", "token": token})
        return controls

    async def _agent_condition_port(self, node: WorkflowNodeRun) -> str:
        decision = await self.session.scalar(
            select(WorkflowControlDecision).where(
                WorkflowControlDecision.target_node_run_id == node.id,
                WorkflowControlDecision.kind == "condition",
                WorkflowControlDecision.status == "committed",
            )
        )
        if decision is None or not isinstance(decision.value, str):
            raise WorkflowEngineError("Agent Condition 缺少已提交的端口选择")
        if decision.value not in decision.allowed_ports:
            raise WorkflowEngineError("Agent Condition 提交了非法端口")
        return decision.value

    async def _agent_loop_continue(
        self, *, scope: WorkflowScopeRun, parent: WorkflowNodeRun
    ) -> bool:
        decision = await self.session.scalar(
            select(WorkflowControlDecision).where(
                WorkflowControlDecision.scope_run_id == scope.id,
                WorkflowControlDecision.target_node_run_id == parent.id,
                WorkflowControlDecision.kind == "loop",
                WorkflowControlDecision.status == "committed",
            )
        )
        if decision is None or not isinstance(decision.value, bool):
            raise WorkflowEngineError("Agent Loop 缺少已提交的继续决定")
        return decision.value

    async def _materialize_system_artifact(
        self,
        *,
        run: WorkflowRun,
        name: str,
        payload: dict[str, Any],
        kind: str,
        node: WorkflowNodeRun | None = None,
        attempt: WorkflowNodeAttempt | None = None,
    ) -> WorkflowArtifact:
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        artifact = WorkflowArtifact(
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            node_run_id=node.id if node is not None else None,
            created_by_attempt_id=attempt.id if attempt is not None else None,
            kind=kind,
            name=name,
            uri="pending://system-artifact",
            mime_type="application/json",
            sha256="0" * 64,
            size_bytes=0,
            status="available",
        )
        self.session.add(artifact)
        await self.session.flush()
        try:
            uri, size_bytes, sha256, mime_type = await artifact_store.put_bytes(
                tenant_id=artifact.tenant_id,
                workflow_run_id=artifact.workflow_run_id,
                artifact_id=artifact.id,
                name=artifact.name,
                content=content,
                mime_type="application/json",
            )
        except ArtifactStoreError:
            await self.session.delete(artifact)
            raise
        artifact.uri = uri
        artifact.size_bytes = size_bytes
        artifact.sha256 = sha256
        artifact.mime_type = mime_type
        # The DSL Artifact quota protects Agent-produced business files.  The
        # Manager-owned JSON envelopes are required for every Run and must not
        # make a small user quota impossible to use.
        if kind not in {"system_input", "system_output"}:
            run.budget = {
                **run.budget,
                "artifact_bytes": int(run.budget.get("artifact_bytes", 0)) + size_bytes,
            }
        return artifact

    async def _invalidate_attempt_artifacts(
        self, run: WorkflowRun, attempt: WorkflowNodeAttempt
    ) -> None:
        writes = list(
            (
                await self.session.scalars(
                    select(WorkflowVariableWrite).where(
                        WorkflowVariableWrite.attempt_id == attempt.id,
                        WorkflowVariableWrite.status.in_(("staged", "committed")),
                    )
                )
            ).all()
        )
        for write in writes:
            write.status = "discarded"
            write.committed_at = None
        decisions = list(
            (
                await self.session.scalars(
                    select(WorkflowControlDecision).where(
                        WorkflowControlDecision.attempt_id == attempt.id,
                        WorkflowControlDecision.status.in_(
                            ("pending", "submitted", "committed")
                        ),
                    )
                )
            ).all()
        )
        for decision in decisions:
            decision.status = "discarded"
            decision.committed_at = None
        reclaimed = await invalidate_attempt_artifacts(self.session, attempt=attempt)
        if reclaimed.available_bytes or reclaimed.staged_bytes:
            run.budget = {
                **run.budget,
                "artifact_bytes": max(
                    0,
                    int(run.budget.get("artifact_bytes", 0))
                    - reclaimed.available_bytes,
                ),
                "artifact_staged_bytes": max(
                    0,
                    int(run.budget.get("artifact_staged_bytes", 0))
                    - reclaimed.staged_bytes,
                ),
            }
            run.updated_at = utcnow()

    async def _ensure_run_dsl_v2(self, run: WorkflowRun) -> bool:
        """Stop every pre-cutover execution before it can use a persisted plan."""
        if not await self._run_uses_dsl_v2(run):
            await self._abort_unsupported_v1_run(run)
            return False
        return True

    async def _run_uses_dsl_v2(self, run: WorkflowRun) -> bool:
        """Read a persisted version without changing its Run state."""
        version = await self.session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.id == run.workflow_version_id,
                WorkflowVersion.tenant_id == run.tenant_id,
            )
        )
        if version is None:
            return False
        try:
            ensure_workflow_dsl_v2(version.definition)
        except WorkflowCompilationError:
            return False
        return True

    async def _abort_unsupported_v1_run(self, run: WorkflowRun) -> None:
        """Revoke persisted v1 state instead of executing or resuming it."""
        if run.status in {"succeeded", "failed", "cancelled"}:
            return
        nodes = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run.id
                    )
                )
            ).all()
        )
        nodes_by_id = {node.id: node for node in nodes}
        attempts = list(
            (
                await self.session.scalars(
                    select(WorkflowNodeAttempt).where(
                        WorkflowNodeAttempt.workflow_run_id == run.id
                    )
                )
            ).all()
        )
        for attempt in attempts:
            await self._invalidate_attempt_artifacts(run, attempt)
            node = nodes_by_id.get(attempt.node_run_id)
            if (
                node is not None
                and attempt.external_run_id
                and attempt.status in {"dispatching", "dispatched"}
            ):
                attempt.status = "dispatched"
                attempt.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
                attempt.error_message = "DSL v1 已停用"
                attempt.updated_at = utcnow()
                node.status = "stop_requested"
                node.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
                node.error_message = "DSL v1 已停用"
                node.updated_at = utcnow()
                await self._enqueue_job(
                    run=run,
                    scope_run_id=node.scope_run_id,
                    node_run_id=node.id,
                    attempt_id=attempt.id,
                    job_type="cancel_hermes",
                    dedupe_key=f"cancel:{attempt.id}",
                    payload={},
                )
                continue
            attempt.status = "abandoned"
            attempt.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
            attempt.error_message = "DSL v1 已停用"
            attempt.finished_at = utcnow()
            attempt.updated_at = utcnow()
        for node in nodes:
            node.variable_state = _snapshot_variable_state(node.input_snapshot)
            node.output = None
            if node.status != "stop_requested":
                node.status = "failed"
                node.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
                node.error_message = "DSL v1 已停用"
                node.finished_at = utcnow()
            node.updated_at = utcnow()
        scopes = list(
            (
                await self.session.scalars(
                    select(WorkflowScopeRun).where(
                        WorkflowScopeRun.workflow_run_id == run.id
                    )
                )
            ).all()
        )
        for scope in scopes:
            scope.status = "failed"
            scope.finished_at = utcnow()
        run.status = "failed"
        run.output = {"final_artifact_ids": []}
        run.attention_reason = "WORKFLOW_DSL_V1_UNSUPPORTED"
        run.finished_at = utcnow()
        run.updated_at = utcnow()
        await append_event(
            self.session,
            run=run,
            event_type="workflow.failed",
            data={"code": "WORKFLOW_DSL_V1_UNSUPPORTED"},
        )

    async def _request_stop_for_unsupported_attempt(
        self,
        *,
        run: WorkflowRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
        external_run_id: str,
    ) -> None:
        """A create response can race the hard cutover; issue a best-effort stop."""
        if not external_run_id:
            return
        attempt.external_run_id = external_run_id
        attempt.status = "dispatched"
        attempt.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
        attempt.error_message = "DSL v1 已停用"
        attempt.updated_at = utcnow()
        node.status = "stop_requested"
        node.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
        node.error_message = "DSL v1 已停用"
        node.updated_at = utcnow()
        await self._enqueue_job(
            run=run,
            scope_run_id=node.scope_run_id,
            node_run_id=node.id,
            attempt_id=attempt.id,
            job_type="cancel_hermes",
            dedupe_key=f"cancel:{attempt.id}",
            payload={},
        )

    def _plan(self, scope: WorkflowScopeRun) -> dict[str, Any]:
        plan = scope.state.get("plan")
        if not isinstance(plan, dict):
            raise WorkflowEngineError("Scope 缺少编译计划")
        return plan

    def _gateway_base_url(self, instance_id: str) -> str:
        route = settings.nineclaw_route_gateway.format(instance_id=instance_id)
        return f"{settings.resolved_manager_traefik_url}{route}"

    async def _run(self, run_id: UUID) -> WorkflowRun:
        item = await self.session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        if item is None:
            raise WorkflowEngineError("工作流运行不存在")
        return item

    async def _locked_run(self, run_id: UUID) -> WorkflowRun:
        item = await self.session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise WorkflowEngineError("工作流运行不存在")
        return item

    async def _scope(self, scope_id: UUID | None) -> WorkflowScopeRun:
        if scope_id is None:
            raise WorkflowEngineError("Scope 不存在")
        item = await self.session.scalar(
            select(WorkflowScopeRun).where(WorkflowScopeRun.id == scope_id)
        )
        if item is None:
            raise WorkflowEngineError("Scope 不存在")
        return item

    async def _node(
        self, run_id: UUID, scope_id: UUID, definition_id: str
    ) -> WorkflowNodeRun:
        item = await self.session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.scope_run_id == scope_id,
                WorkflowNodeRun.node_definition_id == definition_id,
            )
        )
        if item is None:
            raise WorkflowEngineError("节点运行不存在")
        return item

    async def _node_by_id(self, node_id: UUID) -> WorkflowNodeRun:
        item = await self.session.scalar(
            select(WorkflowNodeRun)
            .where(WorkflowNodeRun.id == node_id)
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise WorkflowEngineError("节点运行不存在")
        return item

    async def _edge(
        self, run_id: UUID, scope_id: UUID, definition_id: str
    ) -> WorkflowEdgeRun:
        item = await self.session.scalar(
            select(WorkflowEdgeRun).where(
                WorkflowEdgeRun.workflow_run_id == run_id,
                WorkflowEdgeRun.scope_run_id == scope_id,
                WorkflowEdgeRun.edge_definition_id == definition_id,
            )
        )
        if item is None:
            raise WorkflowEngineError("边运行不存在")
        return item

    async def _attempt(self, attempt_id: UUID) -> WorkflowNodeAttempt:
        item = await self.session.scalar(
            select(WorkflowNodeAttempt).where(WorkflowNodeAttempt.id == attempt_id)
        )
        if item is None:
            raise WorkflowEngineError("节点 Attempt 不存在")
        return item

    async def _job(self, job_id: UUID) -> WorkflowJob:
        item = await self.session.scalar(
            select(WorkflowJob).where(WorkflowJob.id == job_id)
        )
        if item is None:
            raise WorkflowEngineError("工作流 Job 不存在")
        return item

    async def _finish_job(self, job: WorkflowJob) -> None:
        job.status = "succeeded"
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utcnow()


def _build_hermes_messages(
    config: dict[str, Any], input_snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    """Keep user messages free of graph-shaped workflow context.

    The frozen snapshot is intentionally not interpolated into the prompt.
    Hermes receives its task text unchanged and obtains upstream files and
    variables through the Manager-authorized local MCP bridge.
    """
    del input_snapshot
    messages = config.get("messages")
    if isinstance(messages, list):
        return [item for item in messages if isinstance(item, dict)]
    return [{"role": "user", "content": str(config.get("prompt") or "")}]


def _build_workspace_instructions(
    execution_id: str, workspace_token: str, controls: list[dict[str, Any]]
) -> str:
    """Return manager-owned Hermes instructions for one workflow Attempt.

    The execution ID and opaque workspace token are a paired, Attempt-scoped
    Manager authorization. They are deliberately kept out of user messages;
    Manager still verifies the active Attempt and immutable input snapshot on
    every request.
    """
    lines = [
        "<workflow-workspace>",
        f"execution_id: {execution_id}",
        f"workspace_token: {workspace_token}",
        "使用 workspace_list 查看已授权上游 Artifact；使用 workspace_download 下载；",
        "使用 workspace_upload 提交当前节点产物。",
        "使用 variables_list、variables_get、variables_set、variables_set_many 访问工作流变量。",
        "所有工具调用必须携带此 execution_id 和 workspace_token。",
        "工具的本地相对路径位于 /tmp/nineclaw-workspace/" f"{execution_id}/ 下。",
        "</workflow-workspace>",
    ]
    if controls:
        lines.append("<workflow-control>")
        for control in controls:
            if control["kind"] == "condition":
                lines.append(
                    "调用 condition_select_port，"
                    f"token: {control['token']}，可选 port: {', '.join(control['ports'])}。"
                )
            elif control["kind"] == "loop":
                lines.append(
                    "调用 loop_continue，"
                    f"token: {control['token']}，通过 should_continue 指定是否继续。"
                )
        lines.append("</workflow-control>")
    return "\n".join(lines)


def _artifact_metadata(artifact: WorkflowArtifact) -> dict[str, str | int]:
    return {
        "id": str(artifact.id),
        "name": artifact.name,
        "kind": artifact.kind,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def _select_formula_condition_port(
    config: dict[str, Any], context: dict[str, Any]
) -> str:
    return (
        str(config["true_port"])
        if bool(evaluate(config["expression"], context))
        else str(config["false_port"])
    )


def _snapshot_variable_state(source: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(source, dict):
        return {}
    value = source.get("variable_state", source.get("inherited_variable_state", {}))
    if not isinstance(value, dict):
        return {}
    return {
        str(name): dict(entry)
        for name, entry in value.items()
        if isinstance(entry, dict) and "value" in entry
    }


def _uuid_list(value: Any) -> list[UUID]:
    if not isinstance(value, list):
        return []
    result: list[UUID] = []
    for raw in value:
        try:
            result.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return result


def _formula_context(snapshot: Any) -> dict[str, Any]:
    source = snapshot if isinstance(snapshot, dict) else {}
    artifacts = source.get("artifacts")
    return {
        "vars": dict(source.get("variables") or {}),
        "system": {
            "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
            "artifacts": artifacts if isinstance(artifacts, list) else [],
            "iteration_index": (source.get("system") or {}).get("iteration_index"),
        },
    }


def _remote_status(payload: dict[str, Any]) -> str:
    raw = payload.get("status") or payload.get("state") or ""
    return str(raw).strip().lower().replace("-", "_")


def _extract_remote_output(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("output", "result", "data", "response"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {"hermes_run": payload}


def _extract_remote_error(payload: dict[str, Any]) -> str:
    value = (
        payload.get("error")
        or payload.get("message")
        or payload.get("detail")
        or "Hermes Run 执行失败"
    )
    if isinstance(value, dict):
        return str(value.get("message") or value)
    return str(value)

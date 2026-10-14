"""Internal Manager API used only by Runtime-local workspace MCP bridges."""

from __future__ import annotations

from collections.abc import AsyncIterator
import math
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Body,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.workflow import (
    WorkflowArtifact,
    WorkflowControlDecision,
    WorkflowNodeAttempt,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowScopeRun,
    WorkflowVariableWrite,
    WorkflowVersion,
)
from app.services.workflow.artifacts import ArtifactStoreError, artifact_store
from app.services.workflow.compiler import (
    WorkflowCompilationError,
    ensure_workflow_dsl_v2,
)
from app.services.workflow.workspace_auth import (
    bridge_token_is_valid,
    workspace_token_is_valid,
)


router = APIRouter(prefix="/workflow-workspace", tags=["workflow-workspace"])

_INSTANCE_HEADER = "X-Nineclaw-Workspace-Instance"
_WORKSPACE_TOKEN_HEADER = "X-Nineclaw-Workspace-Token"
_TERMINAL_RUN_STATES = {"succeeded", "failed", "cancelled"}
_ACTIVE_NODE_STATES = {"dispatching", "running"}
_ACTIVE_ATTEMPT_STATES = {"dispatching", "dispatched"}


class WorkspaceContext:
    def __init__(
        self,
        *,
        run: WorkflowRun,
        node: WorkflowNodeRun,
        attempt: WorkflowNodeAttempt,
    ) -> None:
        self.run = run
        self.node = node
        self.attempt = attempt


def _unauthorized(detail: str = "工作区 Bridge 未授权") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def _require_bridge_instance(
    authorization: str | None = Header(default=None),
    instance_id: str | None = Header(default=None, alias=_INSTANCE_HEADER),
) -> str:
    if not settings.workflow_workspace_bridge_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="工作区 Bridge 未配置",
        )
    if not instance_id:
        raise _unauthorized()
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not bridge_token_is_valid(
        instance_id=instance_id, token=token
    ):
        raise _unauthorized()
    return instance_id


async def _active_context(
    session: AsyncSession,
    *,
    execution_id: str,
    instance_id: str,
    workspace_token: str | None,
) -> WorkspaceContext:
    # The long-lived Bridge credential identifies the Runtime instance.  The
    # per-Attempt token prevents that same instance from using an unrelated
    # active execution ID belonging to another Hermes run.
    if not workspace_token_is_valid(
        execution_id=execution_id,
        instance_id=instance_id,
        token=workspace_token,
    ):
        # Keep execution IDs non-enumerable to an otherwise valid instance.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作区执行不存在"
        )
    candidate = await session.scalar(
        select(WorkflowNodeAttempt).where(
            WorkflowNodeAttempt.execution_id == execution_id,
            WorkflowNodeAttempt.executor_instance_id == instance_id,
        )
    )
    # Do not distinguish a foreign execution from a missing execution.
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作区执行不存在"
        )
    run = await session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.id == candidate.workflow_run_id,
            WorkflowRun.tenant_id == candidate.tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    node = await session.scalar(
        select(WorkflowNodeRun)
        .where(
            WorkflowNodeRun.id == candidate.node_run_id,
            WorkflowNodeRun.workflow_run_id == candidate.workflow_run_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    attempt = await session.scalar(
        select(WorkflowNodeAttempt)
        .where(
            WorkflowNodeAttempt.id == candidate.id,
            WorkflowNodeAttempt.execution_id == execution_id,
            WorkflowNodeAttempt.executor_instance_id == instance_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None or node is None or attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作区执行不存在"
        )
    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == run.workflow_version_id,
            WorkflowVersion.tenant_id == run.tenant_id,
            WorkflowVersion.workflow_id == run.workflow_id,
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="工作区执行已失效"
        )
    try:
        ensure_workflow_dsl_v2(version.definition)
    except WorkflowCompilationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKFLOW_DSL_V1_UNSUPPORTED",
        ) from exc
    if (
        run.status in _TERMINAL_RUN_STATES
        or run.cancel_requested_at is not None
        or node.active_attempt_id != attempt.id
        or node.status not in _ACTIVE_NODE_STATES
        or attempt.status not in _ACTIVE_ATTEMPT_STATES
        or attempt.error_code in {"HERMES_DISPATCH_UNKNOWN", "STOP_UNCONFIRMED"}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="工作区执行已失效"
        )
    return WorkspaceContext(run=run, node=node, attempt=attempt)


def _snapshot_artifact_ids(value: Any) -> set[UUID]:
    """Read the explicit frozen Artifact IDs; never inspect variable values."""
    found: set[UUID] = set()
    raw_ids = value.get("artifact_ids") if isinstance(value, dict) else None
    if not isinstance(raw_ids, list):
        return found
    for raw_id in raw_ids:
        try:
            found.add(UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    return found


def _artifact_response(artifact: WorkflowArtifact) -> dict[str, str | int]:
    return {
        "artifact_id": str(artifact.id),
        "name": artifact.name,
        "kind": artifact.kind,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def _remaining_artifact_bytes(run: WorkflowRun) -> int:
    maximum = int(run.budget.get("max_artifact_bytes", 0))
    if maximum:
        return (
            maximum
            - int(run.budget.get("artifact_bytes", 0))
            - int(run.budget.get("artifact_staged_bytes", 0))
        )
    return settings.workflow_artifact_max_upload_size


def _remaining_finalized_artifact_bytes(run: WorkflowRun) -> int:
    maximum = int(run.budget.get("max_artifact_bytes", 0))
    if maximum:
        return maximum - int(run.budget.get("artifact_bytes", 0))
    return settings.workflow_artifact_max_upload_size


async def _staged_artifact(
    session: AsyncSession,
    *,
    context: WorkspaceContext,
    artifact_id: UUID,
) -> WorkflowArtifact:
    artifact = await session.scalar(
        select(WorkflowArtifact)
        .where(
            WorkflowArtifact.id == artifact_id,
            WorkflowArtifact.workflow_run_id == context.run.id,
            WorkflowArtifact.created_by_attempt_id == context.attempt.id,
        )
        .with_for_update()
    )
    if artifact is None or artifact.status != "staged":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="暂存产物不存在"
        )
    return artifact


async def _release_upload_reservation(
    session: AsyncSession, *, artifact_id: UUID
) -> None:
    artifact = await session.scalar(
        select(WorkflowArtifact)
        .where(WorkflowArtifact.id == artifact_id)
        .with_for_update()
    )
    if artifact is None or artifact.status != "uploading":
        return
    run = await session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == artifact.workflow_run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is not None:
        run.budget = {
            **run.budget,
            "artifact_staged_bytes": max(
                0,
                int(run.budget.get("artifact_staged_bytes", 0)) - artifact.size_bytes,
            ),
        }
    await session.delete(artifact)
    await session.commit()


async def _variable_definitions(
    session: AsyncSession, *, context: WorkspaceContext
) -> dict[str, dict[str, Any]]:
    scope = await session.scalar(
        select(WorkflowScopeRun).where(
            WorkflowScopeRun.id == context.node.scope_run_id,
            WorkflowScopeRun.workflow_run_id == context.run.id,
        )
    )
    plan = scope.state.get("plan") if scope is not None else None
    definitions = plan.get("variables") if isinstance(plan, dict) else None
    return dict(definitions) if isinstance(definitions, dict) else {}


def _validate_variable_value(definition: dict[str, Any], value: Any) -> bool:
    type_name = definition.get("type")
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return type(value) is int
    if type_name == "number":
        return type(value) in {int, float} and math.isfinite(float(value))
    if type_name == "boolean":
        return type(value) is bool
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "null":
        return value is None
    return False


async def _effective_variables(
    session: AsyncSession, *, context: WorkspaceContext
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    definitions = await _variable_definitions(session, context=context)
    snapshot = context.node.input_snapshot or {}
    values = dict(snapshot.get("variables") or {})
    staged = list(
        (
            await session.scalars(
                select(WorkflowVariableWrite).where(
                    WorkflowVariableWrite.attempt_id == context.attempt.id,
                    WorkflowVariableWrite.status == "staged",
                )
            )
        ).all()
    )
    for write in staged:
        values[write.name] = write.value
    return definitions, values


def _variable_response(
    *, name: str, definition: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    has_value = name in values
    return {
        "name": name,
        "type": definition.get("type"),
        "value": values.get(name),
        "has_value": has_value,
        **(
            {"description": definition["description"]}
            if isinstance(definition.get("description"), str)
            else {}
        ),
    }


async def _stage_variable_values(
    session: AsyncSession,
    *,
    context: WorkspaceContext,
    values: dict[str, Any],
) -> list[dict[str, Any]]:
    definitions = await _variable_definitions(session, context=context)
    for name, value in values.items():
        definition = definitions.get(name)
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="变量未定义",
            )
        if not _validate_variable_value(definition, value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="变量值与定义类型不匹配",
            )
    existing = {
        write.name: write
        for write in (
            await session.scalars(
                select(WorkflowVariableWrite)
                .where(
                    WorkflowVariableWrite.attempt_id == context.attempt.id,
                    WorkflowVariableWrite.name.in_(list(values)),
                )
                .with_for_update()
            )
        ).all()
    }
    for name, value in values.items():
        write = existing.get(name)
        if write is not None:
            if write.status != "staged":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="变量写入已失效"
                )
            write.value = value
            continue
        session.add(
            WorkflowVariableWrite(
                tenant_id=context.run.tenant_id,
                workflow_run_id=context.run.id,
                scope_run_id=context.node.scope_run_id,
                node_run_id=context.node.id,
                attempt_id=context.attempt.id,
                name=name,
                value=value,
            )
        )
    await session.commit()
    _, effective = await _effective_variables(session, context=context)
    return [
        _variable_response(name=name, definition=definitions[name], values=effective)
        for name in sorted(values)
    ]


@router.get("/artifacts")
async def list_workspace_artifacts(
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, list[dict[str, str | int]]]]:
    """List the immutable Artifact closure captured when this node became ready."""
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    allowed_ids = _snapshot_artifact_ids(context.node.input_snapshot or {})
    if not allowed_ids:
        return {"data": {"items": []}}
    artifacts = list(
        (
            await session.scalars(
                select(WorkflowArtifact)
                .where(
                    WorkflowArtifact.id.in_(allowed_ids),
                    WorkflowArtifact.workflow_run_id == context.run.id,
                    WorkflowArtifact.tenant_id == context.run.tenant_id,
                    WorkflowArtifact.status == "available",
                )
                .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
            )
        ).all()
    )
    return {"data": {"items": [_artifact_response(artifact) for artifact in artifacts]}}


@router.get("/variables")
async def list_workspace_variables(
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    definitions, values = await _effective_variables(session, context=context)
    return {
        "data": {
            "items": [
                _variable_response(name=name, definition=definition, values=values)
                for name, definition in sorted(definitions.items())
            ]
        }
    }


@router.post("/variables/set-many")
async def set_many_workspace_variables(
    body: dict[str, Any] = Body(...),
    execution_id: Annotated[str, Query(min_length=1, max_length=128)] = "",
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    raw_values = body.get("values") if isinstance(body, dict) else None
    if set(body) != {"values"} or not isinstance(raw_values, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请求必须仅包含 values 对象",
        )
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    items = await _stage_variable_values(
        session, context=context, values=dict(raw_values)
    )
    return {"data": {"items": items}}


@router.get("/variables/{variable_name}")
async def get_workspace_variable(
    variable_name: str,
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, Any]]:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    definitions, values = await _effective_variables(session, context=context)
    definition = definitions.get(variable_name)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="变量未定义"
        )
    return {
        "data": _variable_response(
            name=variable_name, definition=definition, values=values
        )
    }


@router.put("/variables/{variable_name}")
async def set_workspace_variable(
    variable_name: str,
    body: dict[str, Any] = Body(...),
    execution_id: Annotated[str, Query(min_length=1, max_length=128)] = "",
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, Any]]:
    if set(body) != {"value"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请求必须仅包含 value",
        )
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    items = await _stage_variable_values(
        session, context=context, values={variable_name: body["value"]}
    )
    return {"data": items[0]}


async def _submit_control_decision(
    session: AsyncSession,
    *,
    context: WorkspaceContext,
    token: str,
    kind: str,
    value: Any,
) -> None:
    decision = await session.scalar(
        select(WorkflowControlDecision)
        .where(
            WorkflowControlDecision.attempt_id == context.attempt.id,
            WorkflowControlDecision.token == token,
            WorkflowControlDecision.kind == kind,
        )
        .with_for_update()
    )
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="控制令牌不存在"
        )
    if decision.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="控制决定已提交"
        )
    if kind == "condition" and value not in decision.allowed_ports:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Condition 端口非法",
        )
    decision.value = value
    decision.status = "submitted"
    await session.commit()


@router.post("/condition-selections")
async def submit_condition_selection(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, bool]]:
    if set(body) != {"execution_id", "token", "port"} or not all(
        isinstance(body.get(key), str) and body[key]
        for key in ("execution_id", "token", "port")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Condition 决定参数无效",
        )
    context = await _active_context(
        session,
        execution_id=body["execution_id"],
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    await _submit_control_decision(
        session,
        context=context,
        token=body["token"],
        kind="condition",
        value=body["port"],
    )
    return {"data": {"accepted": True}}


@router.post("/loop-decisions")
async def submit_loop_decision(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, bool]]:
    if (
        set(body) != {"execution_id", "token", "should_continue"}
        or not isinstance(body.get("execution_id"), str)
        or not body["execution_id"]
        or not isinstance(body.get("token"), str)
        or not body["token"]
        or type(body.get("should_continue")) is not bool
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Loop 决定参数无效"
        )
    context = await _active_context(
        session,
        execution_id=body["execution_id"],
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    await _submit_control_decision(
        session,
        context=context,
        token=body["token"],
        kind="loop",
        value=body["should_continue"],
    )
    return {"data": {"accepted": True}}


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def stage_workspace_upload(
    execution_id: Annotated[str, Form(min_length=1, max_length=128)],
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, str | int]]:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    tenant_id = context.run.tenant_id
    workflow_run_id = context.run.id
    node_run_id = context.node.id
    attempt_id = context.attempt.id
    remaining_bytes = _remaining_artifact_bytes(context.run)
    if remaining_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="工作流产物额度已耗尽",
        )
    artifact = WorkflowArtifact(
        tenant_id=tenant_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        created_by_attempt_id=attempt_id,
        name=(file.filename or "artifact").split("/")[-1].split("\\")[-1] or "artifact",
        uri="staged://pending",
        sha256="0" * 64,
        # Reserve the entire currently available budget before accepting a
        # client-controlled stream. The reservation shrinks to actual size
        # after staging and prevents concurrent uncommitted uploads from
        # exhausting Manager disk beyond the Run's configured quota.
        size_bytes=remaining_bytes,
        status="uploading",
    )
    context.run.budget = {
        **context.run.budget,
        "artifact_staged_bytes": int(context.run.budget.get("artifact_staged_bytes", 0))
        + remaining_bytes,
    }
    session.add(artifact)
    await session.commit()
    upload_artifact_id = artifact.id

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(64 * 1024):
            yield chunk

    try:
        staged = await artifact_store.stage_stream(
            tenant_id=artifact.tenant_id,
            workflow_run_id=artifact.workflow_run_id,
            artifact_id=artifact.id,
            name=artifact.name,
            chunks=chunks(),
            mime_type=file.content_type,
            max_bytes=remaining_bytes,
        )
    except ArtifactStoreError as exc:
        await _release_upload_reservation(session, artifact_id=upload_artifact_id)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except BaseException:
        await _release_upload_reservation(session, artifact_id=upload_artifact_id)
        raise
    try:
        context = await _active_context(
            session,
            execution_id=execution_id,
            instance_id=instance_id,
            workspace_token=workspace_token,
        )
        artifact = await session.scalar(
            select(WorkflowArtifact)
            .where(
                WorkflowArtifact.id == upload_artifact_id,
                WorkflowArtifact.workflow_run_id == context.run.id,
                WorkflowArtifact.created_by_attempt_id == context.attempt.id,
                WorkflowArtifact.status == "uploading",
            )
            .with_for_update()
        )
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="上传已失效"
            )
        reserved_bytes = artifact.size_bytes
        artifact.uri = f"staged://{artifact.id}"
        artifact.size_bytes = staged.size_bytes
        artifact.sha256 = staged.sha256
        artifact.mime_type = staged.mime_type
        artifact.node_run_id = context.node.id
        artifact.created_by_attempt_id = context.attempt.id
        artifact.status = "staged"
        context.run.budget = {
            **context.run.budget,
            "artifact_staged_bytes": max(
                0,
                int(context.run.budget.get("artifact_staged_bytes", 0))
                - reserved_bytes
                + staged.size_bytes,
            ),
        }
        await session.commit()
    except BaseException:
        await session.rollback()
        try:
            await artifact_store.discard(staged)
        except ArtifactStoreError:
            pass
        await _release_upload_reservation(session, artifact_id=upload_artifact_id)
        raise
    return {"data": _artifact_response(artifact)}


@router.post("/uploads/{artifact_id}/commit")
async def commit_workspace_upload(
    artifact_id: UUID,
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> dict[str, dict[str, str | int]]:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    artifact = await _staged_artifact(session, context=context, artifact_id=artifact_id)
    remaining_bytes = _remaining_finalized_artifact_bytes(context.run)
    staged = artifact_store.restore_staged(
        tenant_id=artifact.tenant_id,
        workflow_run_id=artifact.workflow_run_id,
        artifact_id=artifact.id,
        name=artifact.name,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        mime_type=artifact.mime_type,
    )
    if artifact.size_bytes > remaining_bytes:
        await artifact_store.discard(staged)
        context.run.budget = {
            **context.run.budget,
            "artifact_staged_bytes": max(
                0,
                int(context.run.budget.get("artifact_staged_bytes", 0))
                - artifact.size_bytes,
            ),
        }
        await session.delete(artifact)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="工作流产物额度已耗尽",
        )
    uri: str | None = None
    try:
        uri, size_bytes, sha256, mime_type = await artifact_store.finalize(staged)
        artifact.uri = uri
        artifact.size_bytes = size_bytes
        artifact.sha256 = sha256
        artifact.mime_type = mime_type
        artifact.status = "available"
        context.run.budget = {
            **context.run.budget,
            "artifact_bytes": int(context.run.budget.get("artifact_bytes", 0))
            + size_bytes,
            "artifact_staged_bytes": max(
                0,
                int(context.run.budget.get("artifact_staged_bytes", 0))
                - artifact.size_bytes,
            ),
        }
        await session.commit()
    except BaseException:
        await session.rollback()
        if uri is None:
            try:
                await artifact_store.discard(staged)
            except ArtifactStoreError:
                pass
        else:
            try:
                await artifact_store.delete(uri)
            except ArtifactStoreError:
                pass
        raise
    return {"data": _artifact_response(artifact)}


@router.delete(
    "/uploads/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def abort_workspace_upload(
    artifact_id: UUID,
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> None:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    artifact = await _staged_artifact(session, context=context, artifact_id=artifact_id)
    staged = artifact_store.restore_staged(
        tenant_id=artifact.tenant_id,
        workflow_run_id=artifact.workflow_run_id,
        artifact_id=artifact.id,
        name=artifact.name,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        mime_type=artifact.mime_type,
    )
    await artifact_store.discard(staged)
    context.run.budget = {
        **context.run.budget,
        "artifact_staged_bytes": max(
            0,
            int(context.run.budget.get("artifact_staged_bytes", 0))
            - artifact.size_bytes,
        ),
    }
    await session.delete(artifact)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/artifacts/{artifact_id}")
async def download_workspace_artifact(
    artifact_id: UUID,
    execution_id: Annotated[str, Query(min_length=1, max_length=128)],
    session: AsyncSession = Depends(get_session),
    instance_id: str = Depends(_require_bridge_instance),
    workspace_token: Annotated[
        str | None, Header(alias=_WORKSPACE_TOKEN_HEADER)
    ] = None,
) -> StreamingResponse:
    context = await _active_context(
        session,
        execution_id=execution_id,
        instance_id=instance_id,
        workspace_token=workspace_token,
    )
    allowed_ids = _snapshot_artifact_ids(context.node.input_snapshot or {})
    if artifact_id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    artifact = await session.scalar(
        select(WorkflowArtifact).where(
            WorkflowArtifact.id == artifact_id,
            WorkflowArtifact.workflow_run_id == context.run.id,
            WorkflowArtifact.tenant_id == context.run.tenant_id,
            WorkflowArtifact.status == "available",
        )
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    uri = artifact.uri
    mime_type = artifact.mime_type
    name = artifact.name
    await session.rollback()
    return StreamingResponse(
        artifact_store.stream_bytes(uri),
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )

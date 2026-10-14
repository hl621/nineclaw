"""Workflow definition, validation and publication API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.instance import ServiceInstance
from app.models.workflow import (
    Workflow,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowScopeRun,
    WorkflowVersion,
)
from app.schemas.workflow import (
    WorkflowArtifactResponse,
    WorkflowApiResponse,
    WorkflowCreateRequest,
    WorkflowDraftUpdateRequest,
    WorkflowMetadataUpdateRequest,
    WorkflowNodeDebugRunRequest,
    WorkflowPublishRequest,
    WorkflowResolveFailedRequest,
    WorkflowResponse,
    WorkflowRetryRequest,
    WorkflowRunResponse,
    WorkflowStartRunRequest,
    WorkflowValidateRequest,
)
from app.services.workflow.compiler import (
    UnsupportedWorkflowDslError,
    WorkflowCompilationError,
    ensure_workflow_dsl_v2,
)
from app.services.workflow.definitions import (
    WorkflowNameConflictError,
    WorkflowNotFoundError,
    create_workflow,
    get_version,
    get_workflow,
    publish_workflow,
    update_draft,
    update_workflow_metadata,
    validate_workflow_definition,
)
from app.services.workflow.engine import (
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowSchemaValidationError,
)
from app.services.workflow.events import (
    MAX_EVENT_SEQUENCE,
    list_events,
    parse_last_event_id,
    public_event_data,
)
from app.services.workflow.node_types import (
    NodeTypeCatalogIntegrityError,
    list_node_type_definitions,
)
from app.services.instance_agent_snapshot import read_manager_resource_snapshot
from app.services.workflow.artifacts import (
    ArtifactStoreError,
    LocalArtifactStore,
    artifact_store,
)


router = APIRouter(prefix="/workflows", tags=["workflows"])
TENANT_HEADER = "X-Tenant-ID"


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    """Temporary trusted-internal tenant partition; authentication is future work."""
    return x_tenant_id or settings.default_tenant_id


def _workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        draft_revision=workflow.draft_revision,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _artifact_response(artifact: WorkflowArtifact) -> WorkflowArtifactResponse:
    return WorkflowArtifactResponse(
        id=artifact.id,
        name=artifact.name,
        kind=artifact.kind,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        created_at=artifact.created_at,
    )


def _run_response(run: WorkflowRun) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        workflow_id=run.workflow_id,
        run_kind=run.run_kind,
        debug_node_id=run.debug_node_id,
        status=run.status,
        input=run.input,
        output=run.output,
        attention_reason=run.attention_reason,
        cancel_requested_at=run.cancel_requested_at,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _compilation_error_detail(exc: WorkflowCompilationError) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "message": "工作流校验失败",
        "issues": [issue.as_dict() for issue in exc.issues],
    }
    if isinstance(exc, UnsupportedWorkflowDslError):
        detail["code"] = exc.code
    return detail


def _require_v2_definition(definition: dict[str, Any]) -> None:
    try:
        ensure_workflow_dsl_v2(definition)
    except WorkflowCompilationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_compilation_error_detail(exc),
        ) from exc


def _agent_catalog_item(instance: ServiceInstance) -> dict[str, Any]:
    """Expose only the Manager-owned, secret-free Agent display projection."""
    snapshot = read_manager_resource_snapshot(instance.config)
    return {
        "instance_id": instance.id,
        "name": instance.name,
        "actual_state": instance.actual_state,
        **snapshot,
    }


async def _owned_run(
    session: AsyncSession, tenant_id: str, run_id: UUID
) -> WorkflowRun:
    run = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.tenant_id == tenant_id
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流运行不存在"
        )
    return run


async def _require_v2_run(session: AsyncSession, run: WorkflowRun) -> None:
    """Reject retired published snapshots before a route mutates Run data."""

    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == run.workflow_version_id,
            WorkflowVersion.tenant_id == run.tenant_id,
            WorkflowVersion.workflow_id == run.workflow_id,
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKFLOW_DSL_V1_UNSUPPORTED",
        )
    try:
        ensure_workflow_dsl_v2(version.definition)
    except WorkflowCompilationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKFLOW_DSL_V1_UNSUPPORTED",
        ) from exc


async def _owned_node(
    session: AsyncSession, tenant_id: str, node_run_id: UUID
) -> tuple[WorkflowRun, WorkflowNodeRun]:
    node = await session.scalar(
        select(WorkflowNodeRun).where(
            WorkflowNodeRun.id == node_run_id, WorkflowNodeRun.tenant_id == tenant_id
        )
    )
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="节点运行不存在"
        )
    run = await _owned_run(session, tenant_id, node.workflow_run_id)
    return run, node


async def _latest_published_version(
    session: AsyncSession, *, tenant_id: str, workflow: Workflow
) -> Any:
    """Resolve the only externally selectable version: the latest publication."""
    if workflow.current_version_number is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="工作流尚未发布"
        )
    try:
        version = await get_version(
            session,
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=workflow.current_version_number,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="工作流发布状态无效"
        ) from exc
    _require_v2_definition(version.definition)
    return version


@router.get("", response_model=WorkflowApiResponse, summary="List workflow definitions")
async def list_workflows(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    workflows = list(
        (
            await session.scalars(
                select(Workflow)
                .where(Workflow.tenant_id == tenant_id)
                .order_by(Workflow.updated_at.desc())
            )
        ).all()
    )
    items = [_workflow_response(item).model_dump(mode="json") for item in workflows]
    return WorkflowApiResponse(data={"items": items, "total": len(items)})


@router.post(
    "",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workflow draft",
)
async def create_workflow_endpoint(
    body: WorkflowCreateRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await create_workflow(
            session,
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            definition=body.definition,
        )
    except WorkflowCompilationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_compilation_error_detail(exc),
        ) from exc
    except WorkflowNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data=_workflow_response(workflow).model_dump(mode="json")
    )


@router.get(
    "/node-types",
    response_model=WorkflowApiResponse,
    summary="List registered workflow node types",
)
async def list_workflow_node_types(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    """Return the persisted editor catalog without reading a workflow or Hermes."""

    del tenant_id  # Keep the existing trusted-internal tenant-header contract.
    try:
        items = await list_node_type_definitions(session)
    except (NodeTypeCatalogIntegrityError, ProgrammingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="工作流节点类型目录未初始化或不完整",
        ) from exc
    return WorkflowApiResponse(data={"items": items, "total": len(items)})


@router.get(
    "/agent-catalog",
    response_model=WorkflowApiResponse,
    summary="List Manager-known Hermes Agent configuration snapshots",
)
async def list_agent_catalog(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    """Return a no-network catalog suitable for an Agent node inspector."""
    instances = list(
        (
            await session.scalars(
                select(ServiceInstance)
                .where(ServiceInstance.tenant_id == tenant_id)
                .order_by(ServiceInstance.name, ServiceInstance.id)
            )
        ).all()
    )
    return WorkflowApiResponse(
        data={
            "items": [_agent_catalog_item(instance) for instance in instances],
            "total": len(instances),
        }
    )


@router.get(
    "/{workflow_id}", response_model=WorkflowApiResponse, summary="Get a workflow draft"
)
async def get_workflow_endpoint(
    workflow_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    _require_v2_definition(workflow.draft_definition)
    return WorkflowApiResponse(
        data={
            **_workflow_response(workflow).model_dump(mode="json"),
            "draft_definition": workflow.draft_definition,
        }
    )


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowApiResponse,
    summary="Update workflow metadata",
)
async def update_workflow_metadata_endpoint(
    workflow_id: UUID,
    body: WorkflowMetadataUpdateRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    if body.name is None and body.description is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少提供 name 或 description",
        )
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
        _require_v2_definition(workflow.draft_definition)
        workflow = await update_workflow_metadata(
            session,
            workflow=workflow,
            name=body.name,
            description=body.description,
            expected_draft_revision=body.expected_draft_revision,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    except WorkflowNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data=_workflow_response(workflow).model_dump(mode="json")
    )


@router.put(
    "/{workflow_id}/draft",
    response_model=WorkflowApiResponse,
    summary="Replace workflow draft",
)
async def update_workflow_draft(
    workflow_id: UUID,
    body: WorkflowDraftUpdateRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    try:
        workflow = await update_draft(
            session,
            workflow=workflow,
            definition=body.definition,
            expected_draft_revision=body.expected_draft_revision,
        )
    except WorkflowCompilationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_compilation_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data=_workflow_response(workflow).model_dump(mode="json")
    )


@router.post(
    "/{workflow_id}/validate",
    response_model=WorkflowApiResponse,
    summary="Validate workflow DSL",
)
async def validate_workflow(
    workflow_id: UUID,
    body: WorkflowValidateRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    definition = (
        body.definition if body.definition is not None else workflow.draft_definition
    )
    try:
        compiled = await validate_workflow_definition(
            session, tenant_id=tenant_id, definition=definition
        )
    except WorkflowCompilationError as exc:
        return WorkflowApiResponse(
            code=1,
            message="工作流校验失败",
            data={
                "valid": False,
                "code": (
                    exc.code if isinstance(exc, UnsupportedWorkflowDslError) else None
                ),
                "issues": [issue.as_dict() for issue in exc.issues],
            },
        )
    return WorkflowApiResponse(
        data={
            "valid": True,
            "checksum": compiled.checksum,
            "compiled_plan": compiled.plan,
        }
    )


@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowApiResponse,
    summary="Publish immutable workflow version",
)
async def publish_workflow_endpoint(
    workflow_id: UUID,
    body: WorkflowPublishRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
        await publish_workflow(
            session,
            workflow=workflow,
            expected_draft_revision=body.expected_draft_revision,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    except WorkflowCompilationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_compilation_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data={"workflow_id": str(workflow_id), "published": True}
    )


@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a workflow run",
)
async def start_workflow_run(
    workflow_id: UUID,
    body: WorkflowStartRunRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
        version = await _latest_published_version(
            session, tenant_id=tenant_id, workflow=workflow
        )
        run = await WorkflowEngine(session).create_run(
            tenant_id=tenant_id,
            workflow=workflow,
            version=version,
            workflow_input=body.input,
        )
        await session.commit()
        await session.refresh(run)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    return WorkflowApiResponse(data=_run_response(run).model_dump(mode="json"))


@router.post(
    "/{workflow_id}/node-debug-runs",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a single-node Hermes debug run",
)
async def start_node_debug_run(
    workflow_id: UUID,
    body: WorkflowNodeDebugRunRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        workflow = await get_workflow(session, tenant_id, workflow_id)
        version = await _latest_published_version(
            session, tenant_id=tenant_id, workflow=workflow
        )
        run = await WorkflowEngine(session).create_node_debug_run(
            tenant_id=tenant_id,
            workflow=workflow,
            version=version,
            node_id=body.node_id,
            node_input=body.input,
        )
        await session.commit()
        await session.refresh(run)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    except WorkflowSchemaValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": exc.code,
                "issues": [issue.as_dict() for issue in exc.issues],
            },
        ) from exc
    except WorkflowEngineError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(data=_run_response(run).model_dump(mode="json"))


@router.get(
    "/{workflow_id}/runs",
    response_model=WorkflowApiResponse,
    summary="List workflow runs",
)
async def list_workflow_runs(
    workflow_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    run_status: str | None = Query(
        default=None, alias="status", min_length=1, max_length=32
    ),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        await get_workflow(session, tenant_id, workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流不存在"
        ) from exc
    filters = [
        WorkflowRun.tenant_id == tenant_id,
        WorkflowRun.workflow_id == workflow_id,
    ]
    if run_status is not None:
        filters.append(WorkflowRun.status == run_status)
    offset = (page - 1) * page_size
    total = int(
        await session.scalar(
            select(func.count()).select_from(WorkflowRun).where(*filters)
        )
        or 0
    )
    runs = list(
        (
            await session.scalars(
                select(WorkflowRun)
                .where(*filters)
                .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )
    return WorkflowApiResponse(
        data={
            "items": [_run_response(run).model_dump(mode="json") for run in runs],
            "total": total,
            "page": page,
            "page_size": page_size,
            "status": run_status,
        }
    )


@router.get(
    "/runs/{run_id}", response_model=WorkflowApiResponse, summary="Get workflow run"
)
async def get_workflow_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    run = await _owned_run(session, tenant_id, run_id)
    owned_run_id = run.id
    nodes = list(
        (
            await session.scalars(
                select(WorkflowNodeRun)
                .where(
                    WorkflowNodeRun.workflow_run_id == run.id,
                    WorkflowNodeRun.tenant_id == tenant_id,
                )
                .order_by(WorkflowNodeRun.created_at)
            )
        ).all()
    )
    return WorkflowApiResponse(
        data={
            **_run_response(run).model_dump(mode="json"),
            "nodes": [
                {
                    "id": str(node.id),
                    "node_definition_id": node.node_definition_id,
                    "node_type": node.node_type,
                    "status": node.status,
                    "input_snapshot": node.input_snapshot,
                    "output": node.output,
                    "generation": node.generation,
                    "error_code": node.error_code,
                    "error_message": node.error_message,
                }
                for node in nodes
            ],
        }
    )


@router.get(
    "/runs/{run_id}/workspace",
    response_model=WorkflowApiResponse,
    summary="Get Agent workspace artifacts and final artifacts",
)
async def get_workflow_workspace(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    """Project workspace outputs by actual Node Run, never by storage location."""
    run = await _owned_run(session, tenant_id, run_id)
    nodes = list(
        (
            await session.scalars(
                select(WorkflowNodeRun)
                .where(
                    WorkflowNodeRun.workflow_run_id == run.id,
                    WorkflowNodeRun.tenant_id == tenant_id,
                    WorkflowNodeRun.node_type == "hermes_agent",
                )
                .order_by(WorkflowNodeRun.created_at, WorkflowNodeRun.id)
            )
        ).all()
    )
    scopes = {
        scope.id: scope
        for scope in (
            await session.scalars(
                select(WorkflowScopeRun).where(
                    WorkflowScopeRun.workflow_run_id == run.id,
                    WorkflowScopeRun.tenant_id == tenant_id,
                )
            )
        ).all()
    }
    active_attempt_ids = {
        node.active_attempt_id for node in nodes if node.active_attempt_id is not None
    }
    artifacts_by_attempt: dict[UUID, list[WorkflowArtifact]] = {}
    if active_attempt_ids:
        artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact)
                    .where(
                        WorkflowArtifact.tenant_id == tenant_id,
                        WorkflowArtifact.workflow_run_id == run.id,
                        WorkflowArtifact.status == "available",
                        WorkflowArtifact.created_by_attempt_id.in_(active_attempt_ids),
                    )
                    .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                )
            ).all()
        )
        for artifact in artifacts:
            if artifact.created_by_attempt_id is not None:
                artifacts_by_attempt.setdefault(
                    artifact.created_by_attempt_id, []
                ).append(artifact)

    final_ids: list[UUID] = []
    if run.run_kind == "workflow" and run.status == "succeeded":
        raw_final_ids = (run.output or {}).get("final_artifact_ids", [])
        if isinstance(raw_final_ids, list):
            for value in raw_final_ids:
                try:
                    artifact_id = UUID(str(value))
                except (TypeError, ValueError):
                    continue
                if artifact_id not in final_ids:
                    final_ids.append(artifact_id)
    final_by_id: dict[UUID, WorkflowArtifact] = {}
    if final_ids:
        final_artifacts = list(
            (
                await session.scalars(
                    select(WorkflowArtifact).where(
                        WorkflowArtifact.id.in_(final_ids),
                        WorkflowArtifact.tenant_id == tenant_id,
                        WorkflowArtifact.workflow_run_id == run.id,
                        WorkflowArtifact.status == "available",
                    )
                )
            ).all()
        )
        final_by_id = {artifact.id: artifact for artifact in final_artifacts}

    return WorkflowApiResponse(
        data={
            "agent_nodes": [
                {
                    "node_run_id": str(node.id),
                    "node_definition_id": node.node_definition_id,
                    "status": node.status,
                    "scope": {
                        "id": str(node.scope_run_id),
                        "kind": (
                            scopes[node.scope_run_id].kind
                            if node.scope_run_id in scopes
                            else "unknown"
                        ),
                        "iteration_index": (
                            scopes[node.scope_run_id].iteration_index
                            if node.scope_run_id in scopes
                            else None
                        ),
                        "parent_node_run_id": (
                            str(scopes[node.scope_run_id].parent_node_run_id)
                            if node.scope_run_id in scopes
                            and scopes[node.scope_run_id].parent_node_run_id is not None
                            else None
                        ),
                    },
                    "artifacts": [
                        _artifact_response(artifact).model_dump(mode="json")
                        for artifact in artifacts_by_attempt.get(
                            node.active_attempt_id, []
                        )
                    ],
                }
                for node in nodes
            ],
            "final_artifacts": [
                _artifact_response(final_by_id[artifact_id]).model_dump(mode="json")
                for artifact_id in final_ids
                if artifact_id in final_by_id
            ],
        }
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=WorkflowApiResponse,
    summary="Cancel a workflow run",
)
async def cancel_workflow_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    run = await _owned_run(session, tenant_id, run_id)
    try:
        await WorkflowEngine(session).request_cancel(run=run, requested_by=tenant_id)
        await session.commit()
        await session.refresh(run)
    except WorkflowEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(data=_run_response(run).model_dump(mode="json"))


@router.get(
    "/runs/{run_id}/events",
    response_model=WorkflowApiResponse,
    summary="List workflow lifecycle events",
)
async def get_workflow_events(
    run_id: UUID,
    after_sequence: int = Query(default=0, ge=0, le=MAX_EVENT_SEQUENCE),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    await _owned_run(session, tenant_id, run_id)
    events = await list_events(
        session,
        tenant_id=tenant_id,
        run_id=run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return WorkflowApiResponse(
        data={
            "items": [
                {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "data": public_event_data(event.event_type, event.data),
                    "created_at": event.created_at.isoformat(),
                }
                for event in events
            ],
            "total": len(events),
            "next_after_sequence": (
                events[-1].sequence if len(events) == limit else None
            ),
        }
    )


@router.get(
    "/runs/{run_id}/events/stream", summary="Replay workflow lifecycle events over SSE"
)
async def stream_workflow_events(
    run_id: UUID,
    request: Request,
    after_sequence: int = Query(default=0, ge=0, le=MAX_EVENT_SEQUENCE),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> EventSourceResponse:
    await _owned_run(session, tenant_id, run_id)
    header_sequence = parse_last_event_id(request.headers.get("Last-Event-ID"))
    if header_sequence is not None:
        after_sequence = max(after_sequence, header_sequence)

    # The stream itself uses fresh short-lived sessions. Do not retain the
    # request dependency session for the lifetime of an SSE connection.
    await session.rollback()

    async def event_generator():
        sequence = after_sequence
        while not await request.is_disconnected():
            # A new dependency session is required for every poll; the request
            # session can be closed by FastAPI once the response starts.
            async with async_session_maker() as event_session:
                events = await list_events(
                    event_session,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    after_sequence=sequence,
                    limit=100,
                )
                run_status = await event_session.scalar(
                    select(WorkflowRun.status).where(
                        WorkflowRun.id == run_id,
                        WorkflowRun.tenant_id == tenant_id,
                    )
                )
            for event in events:
                sequence = event.sequence
                yield {
                    "id": str(event.sequence),
                    "event": event.event_type,
                    "data": json.dumps(
                        {
                            "sequence": event.sequence,
                            "event_type": event.event_type,
                            "data": public_event_data(event.event_type, event.data),
                        },
                        ensure_ascii=False,
                    ),
                }
            if run_status in {"succeeded", "failed", "cancelled"}:
                return
            if len(events) == 100:
                continue
            await asyncio.sleep(settings.workflow_scheduler_poll_seconds)

    return EventSourceResponse(
        event_generator(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        ping=15,
    )


@router.post(
    "/node-runs/{node_run_id}/retry",
    response_model=WorkflowApiResponse,
    summary="Retry an uncertain node",
)
async def retry_node_run(
    node_run_id: UUID,
    body: WorkflowRetryRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    if not body.confirm_duplicate_side_effect_risk:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="必须确认可能重复产生副作用",
        )
    run, node = await _owned_node(session, tenant_id, node_run_id)
    try:
        await WorkflowEngine(session).retry_uncertain(run=run, node=node)
        await session.commit()
    except WorkflowEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data={
            "node_run_id": str(node.id),
            "status": node.status,
            "generation": node.generation,
        }
    )


@router.post(
    "/node-runs/{node_run_id}/mark-failed",
    response_model=WorkflowApiResponse,
    summary="Resolve an uncertain node as failed",
)
async def mark_node_run_failed(
    node_run_id: UUID,
    body: WorkflowResolveFailedRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    run, node = await _owned_node(session, tenant_id, node_run_id)
    try:
        await WorkflowEngine(session).resolve_uncertain_as_failed(
            run=run, node=node, reason=body.reason
        )
        await session.commit()
    except WorkflowEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return WorkflowApiResponse(
        data={"node_run_id": str(node.id), "status": node.status}
    )


@router.post(
    "/runs/{run_id}/artifacts",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload workflow artifact",
)
async def upload_workflow_artifact(
    run_id: UUID,
    file: UploadFile = File(...),
    node_run_id: UUID | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    run = await _owned_run(session, tenant_id, run_id)
    owned_run_id = run.id
    if node_run_id is not None:
        _, node = await _owned_node(session, tenant_id, node_run_id)
        if node.workflow_run_id != run.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="节点不属于该工作流运行",
            )
    # Persist the upload reservation before consuming a client-controlled
    # stream.  This keeps a durable DB reference throughout the crash window
    # from local staging through final object creation.
    await session.rollback()
    safe_name = Path(file.filename or "artifact").name or "artifact"
    run = await session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == owned_run_id, WorkflowRun.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="工作流运行不存在"
        )
    await _require_v2_run(session, run)
    current_bytes = int(run.budget.get("artifact_bytes", 0))
    staged_bytes = int(run.budget.get("artifact_staged_bytes", 0))
    maximum_bytes = int(run.budget.get("max_artifact_bytes", 0))
    remaining_bytes = (
        maximum_bytes - current_bytes - staged_bytes
        if maximum_bytes
        else settings.workflow_artifact_max_upload_size
    )
    if remaining_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="工作流产物额度已耗尽",
        )
    artifact = WorkflowArtifact(
        tenant_id=tenant_id,
        workflow_run_id=owned_run_id,
        node_run_id=node_run_id,
        name=safe_name,
        uri="staged://pending",
        sha256="0" * 64,
        size_bytes=remaining_bytes,
        status="uploading",
    )
    run.budget = {
        **run.budget,
        "artifact_staged_bytes": staged_bytes + remaining_bytes,
    }
    session.add(artifact)
    await session.commit()
    artifact_id = artifact.id

    async def release_upload_reservation() -> None:
        """Remove an uncommitted upload record and return its reservation."""
        await session.rollback()
        locked_run = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == owned_run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        pending = await session.scalar(
            select(WorkflowArtifact)
            .where(WorkflowArtifact.id == artifact_id)
            .with_for_update()
        )
        if pending is None:
            return
        if locked_run is not None:
            budget_key = (
                "artifact_bytes"
                if pending.status == "available"
                else "artifact_staged_bytes"
            )
            locked_run.budget = {
                **locked_run.budget,
                budget_key: max(
                    0,
                    int(locked_run.budget.get(budget_key, 0)) - pending.size_bytes,
                ),
            }
        await session.delete(pending)
        await session.commit()

    async def chunks():
        while chunk := await file.read(64 * 1024):
            yield chunk

    try:
        staged = await artifact_store.stage_stream(
            tenant_id=tenant_id,
            workflow_run_id=owned_run_id,
            artifact_id=artifact.id,
            name=artifact.name,
            chunks=chunks(),
            mime_type=file.content_type,
            max_bytes=remaining_bytes,
        )
    except ArtifactStoreError as exc:
        await release_upload_reservation()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except BaseException:
        await release_upload_reservation()
        raise

    try:
        run = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == owned_run_id, WorkflowRun.tenant_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        artifact = await session.scalar(
            select(WorkflowArtifact)
            .where(
                WorkflowArtifact.id == artifact_id,
                WorkflowArtifact.status == "uploading",
            )
            .with_for_update()
        )
        if run is None or artifact is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="上传已失效"
            )
        reserved_bytes = artifact.size_bytes
        artifact.uri = f"staged://{artifact.id}"
        artifact.size_bytes = staged.size_bytes
        artifact.sha256 = staged.sha256
        artifact.mime_type = staged.mime_type
        artifact.status = "staged"
        run.budget = {
            **run.budget,
            "artifact_staged_bytes": max(
                0,
                int(run.budget.get("artifact_staged_bytes", 0))
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
        await release_upload_reservation()
        raise

    uri: str | None = None
    try:
        run = await session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == owned_run_id, WorkflowRun.tenant_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        artifact = await session.scalar(
            select(WorkflowArtifact)
            .where(
                WorkflowArtifact.id == artifact_id,
                WorkflowArtifact.status == "staged",
            )
            .with_for_update()
        )
        if run is None or artifact is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="上传已失效"
            )
        current_bytes = int(run.budget.get("artifact_bytes", 0))
        maximum_bytes = int(run.budget.get("max_artifact_bytes", 0))
        remaining_finalized_bytes = (
            maximum_bytes - current_bytes
            if maximum_bytes
            else settings.workflow_artifact_max_upload_size
        )
        if artifact.size_bytes > remaining_finalized_bytes:
            await artifact_store.discard(staged)
            run.budget = {
                **run.budget,
                "artifact_staged_bytes": max(
                    0,
                    int(run.budget.get("artifact_staged_bytes", 0))
                    - artifact.size_bytes,
                ),
            }
            await session.delete(artifact)
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="工作流产物额度已耗尽",
            )
        uri, size_bytes, sha256, mime_type = await artifact_store.finalize(staged)
        artifact.uri = uri
        artifact.size_bytes = size_bytes
        artifact.sha256 = sha256
        artifact.mime_type = mime_type
        artifact.status = "available"
        run.budget = {
            **run.budget,
            "artifact_bytes": current_bytes + size_bytes,
            "artifact_staged_bytes": max(
                0,
                int(run.budget.get("artifact_staged_bytes", 0)) - size_bytes,
            ),
        }
        await session.commit()
    except BaseException:
        await session.rollback()
        try:
            if uri is None:
                await artifact_store.discard(staged)
            else:
                await artifact_store.delete(uri)
        except ArtifactStoreError:
            pass
        await release_upload_reservation()
        raise
    return WorkflowApiResponse(
        data={
            "id": str(artifact.id),
            "name": artifact.name,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }
    )


@router.get(
    "/runs/{run_id}/artifacts",
    response_model=WorkflowApiResponse,
    summary="List available workflow artifacts",
)
async def list_workflow_artifacts(
    run_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    node_run_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    run = await _owned_run(session, tenant_id, run_id)
    filters = [
        WorkflowArtifact.tenant_id == tenant_id,
        WorkflowArtifact.workflow_run_id == run.id,
        WorkflowArtifact.status == "available",
    ]
    if node_run_id is not None:
        filters.append(WorkflowArtifact.node_run_id == node_run_id)
    offset = (page - 1) * page_size
    total = int(
        await session.scalar(
            select(func.count()).select_from(WorkflowArtifact).where(*filters)
        )
        or 0
    )
    artifacts = list(
        (
            await session.scalars(
                select(WorkflowArtifact)
                .where(*filters)
                .order_by(
                    WorkflowArtifact.created_at.desc(), WorkflowArtifact.id.desc()
                )
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )
    return WorkflowApiResponse(
        data={
            "items": [
                _artifact_response(artifact).model_dump(mode="json")
                for artifact in artifacts
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "node_run_id": str(node_run_id) if node_run_id is not None else None,
        }
    )


@router.get(
    "/runs/{run_id}/artifacts/{artifact_id}",
    summary="Download workflow artifact",
    response_model=None,
)
async def download_workflow_artifact(
    run_id: UUID,
    artifact_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> FileResponse | StreamingResponse:
    await _owned_run(session, tenant_id, run_id)
    artifact = await session.scalar(
        select(WorkflowArtifact).where(
            WorkflowArtifact.id == artifact_id,
            WorkflowArtifact.workflow_run_id == run_id,
            WorkflowArtifact.tenant_id == tenant_id,
            WorkflowArtifact.status == "available",
        )
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产物不存在")
    if isinstance(artifact_store, LocalArtifactStore):
        try:
            path = await artifact_store.file_path(artifact.uri)
        except ArtifactStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        return FileResponse(
            path,
            media_type=artifact.mime_type,
            filename=artifact.name,
        )
    return StreamingResponse(
        artifact_store.stream_bytes(artifact.uri),
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )

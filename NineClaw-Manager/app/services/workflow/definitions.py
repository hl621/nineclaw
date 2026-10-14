"""Workflow definition CRUD and immutable publication service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import ServiceInstance
from app.models.workflow import Workflow, WorkflowVersion, utcnow
from app.services.workflow.compiler import (
    CompiledWorkflow,
    CompilationIssue,
    WorkflowCompilationError,
    compile_workflow,
)


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowNameConflictError(ValueError):
    """Stable domain error for the per-tenant workflow-name constraint."""

    code = "WORKFLOW_NAME_CONFLICT"

    def __init__(self) -> None:
        super().__init__("工作流名称已存在")


async def get_workflow(
    session: AsyncSession, tenant_id: str, workflow_id: UUID
) -> Workflow:
    workflow = await session.scalar(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
        )
    )
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))
    return workflow


async def create_workflow(
    session: AsyncSession,
    *,
    tenant_id: str,
    name: str,
    description: str,
    definition: dict,
) -> Workflow:
    compiled = await validate_workflow_definition(
        session, tenant_id=tenant_id, definition=definition
    )
    workflow = Workflow(
        tenant_id=tenant_id,
        name=name.strip(),
        description=description.strip(),
        draft_definition=compiled.definition,
    )
    session.add(workflow)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise WorkflowNameConflictError() from exc
    await session.refresh(workflow)
    return workflow


async def update_workflow_metadata(
    session: AsyncSession,
    *,
    workflow: Workflow,
    name: str | None,
    description: str | None,
    expected_draft_revision: int,
) -> Workflow:
    """Atomically update editable metadata under the workflow revision lock."""
    workflow = await _locked_workflow(session, workflow)
    if workflow.draft_revision != expected_draft_revision:
        raise ValueError("草稿版本已变化，请重新读取后更新")
    if name is not None:
        workflow.name = name.strip()
    if description is not None:
        workflow.description = description.strip()
    workflow.draft_revision += 1
    workflow.updated_at = utcnow()
    session.add(workflow)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise WorkflowNameConflictError() from exc
    await session.refresh(workflow)
    return workflow


async def update_draft(
    session: AsyncSession,
    *,
    workflow: Workflow,
    definition: dict,
    expected_draft_revision: int,
) -> Workflow:
    workflow = await _locked_workflow(session, workflow)
    if workflow.draft_revision != expected_draft_revision:
        raise ValueError("草稿版本已变化，请重新读取后更新")
    compiled = await validate_workflow_definition(
        session, tenant_id=workflow.tenant_id, definition=definition
    )
    # Assign a fresh object. SQLAlchemy does not reliably detect nested JSONB mutation.
    workflow.draft_definition = compiled.definition
    workflow.draft_revision += 1
    workflow.updated_at = utcnow()
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def publish_workflow(
    session: AsyncSession,
    *,
    workflow: Workflow,
    expected_draft_revision: int,
) -> tuple[WorkflowVersion, CompiledWorkflow]:
    workflow = await _locked_workflow(session, workflow)
    if workflow.draft_revision != expected_draft_revision:
        raise ValueError("草稿版本已变化，请重新读取后发布")

    compiled = await validate_workflow_definition(
        session, tenant_id=workflow.tenant_id, definition=workflow.draft_definition
    )
    next_number = (
        int(
            await session.scalar(
                select(
                    func.coalesce(func.max(WorkflowVersion.version_number), 0)
                ).where(WorkflowVersion.workflow_id == workflow.id)
            )
            or 0
        )
        + 1
    )
    version = WorkflowVersion(
        tenant_id=workflow.tenant_id,
        workflow_id=workflow.id,
        version_number=next_number,
        definition=compiled.definition,
        compiled_plan=compiled.plan,
        checksum=compiled.checksum,
    )
    workflow.current_version_number = next_number
    workflow.updated_at = utcnow()
    session.add(version)
    session.add(workflow)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError("发布版本冲突，请重新读取后发布") from exc
    await session.refresh(version)
    return version, compiled


async def _locked_workflow(session: AsyncSession, workflow: Workflow) -> Workflow:
    locked = await session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow.id, Workflow.tenant_id == workflow.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise WorkflowNotFoundError(str(workflow.id))
    return locked


async def get_version(
    session: AsyncSession,
    *,
    tenant_id: str,
    workflow_id: UUID,
    version_number: int,
) -> WorkflowVersion:
    version = await session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.tenant_id == tenant_id,
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version_number == version_number,
        )
    )
    if version is None:
        raise WorkflowNotFoundError(f"{workflow_id}@{version_number}")
    return version


async def validate_workflow_definition(
    session: AsyncSession,
    *,
    tenant_id: str,
    definition: dict,
) -> CompiledWorkflow:
    """Compile a definition and verify every referenced Hermes instance is owned.

    This is intentionally used by create, draft replace, validate and publish so
    a definition which cannot be executed for this tenant is never persisted.
    Instance running state is deliberately excluded: an owned stopped instance
    may become runnable after the workflow is saved.
    """
    compiled = compile_workflow(definition)
    references = _hermes_instance_references(compiled.definition)
    if not references:
        return compiled
    instance_ids = {instance_id for _, instance_id in references}
    owned = set(
        (
            await session.scalars(
                select(ServiceInstance.id).where(
                    ServiceInstance.tenant_id == tenant_id,
                    ServiceInstance.id.in_(instance_ids),
                )
            )
        ).all()
    )
    missing = instance_ids - owned
    if missing:
        raise WorkflowCompilationError(
            [
                CompilationIssue(path, "Hermes 实例不存在或不属于当前租户")
                for path, instance_id in references
                if instance_id in missing
            ]
        )
    return compiled


def _hermes_instance_references(
    definition: dict,
    *,
    path_prefix: str = "nodes",
) -> list[tuple[str, str]]:
    """Return every Hermes config reference, including Loop Body definitions."""
    references: list[tuple[str, str]] = []
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return references
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        path = f"{path_prefix}[{index}]"
        if node.get("type") == "hermes_agent":
            instance_id = (node.get("config") or {}).get("instance_id")
            if isinstance(instance_id, str):
                references.append((f"{path}.config.instance_id", instance_id))
        if node.get("type") == "loop":
            body = (node.get("config") or {}).get("body")
            if isinstance(body, dict):
                references.extend(
                    _hermes_instance_references(
                        body, path_prefix=f"{path}.config.body.nodes"
                    )
                )
    return references

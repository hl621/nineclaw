"""Persistent workflow lifecycle event helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowEvent, WorkflowRun, utcnow


_PUBLIC_EVENT_FIELDS: dict[str, frozenset[str]] = {
    "workflow.started": frozenset({"workflow_id", "run_kind", "debug_node_id"}),
    "workflow.cancel_requested": frozenset(),
    "workflow.cancelled": frozenset(),
    "workflow.failed": frozenset({"code"}),
    "workflow.succeeded": frozenset({"output"}),
    "workflow.attention_required": frozenset({"message"}),
    "workflow.attention_resolved": frozenset(),
    "node.ready": frozenset({"node_run_id", "node_id", "manual_retry"}),
    "node.dispatching": frozenset({"node_run_id", "node_id"}),
    "node.started": frozenset({"node_run_id", "node_id"}),
    "node.stop_requested": frozenset({"node_run_id", "node_id"}),
    "node.stop_unconfirmed": frozenset({"node_run_id", "message"}),
    "node.succeeded": frozenset({"node_run_id", "node_id"}),
    "node.failed": frozenset({"node_run_id", "node_id", "code", "message"}),
    "node.cancelled": frozenset({"node_run_id", "node_id"}),
    "node.uncertain": frozenset({"node_run_id", "message"}),
    "node.blocked": frozenset({"node_run_id", "node_id"}),
    "node.skipped": frozenset({"node_run_id", "node_id"}),
    "loop.iteration.started": frozenset({"node_run_id", "iteration"}),
    "loop.iteration.completed": frozenset({"node_run_id", "iteration", "continue"}),
    "attempt.result_ignored": frozenset({"reason"}),
    "attempt.stop_result_ignored": frozenset(),
}
MAX_EVENT_SEQUENCE = 2_147_483_647


def public_event_data(event_type: str, data: Any) -> dict[str, Any]:
    """Return the public event projection, dropping unknown event payloads.

    The event table is an internal audit record and can contain Hermes or
    scheduling identifiers.  HTTP polling and SSE use this narrow projection
    so adding a private field to an internal event cannot expose it by
    accident.
    """
    if not isinstance(data, dict):
        return {}
    allowed = _PUBLIC_EVENT_FIELDS.get(event_type, frozenset())
    return {key: value for key, value in data.items() if key in allowed}


def parse_last_event_id(value: str | None) -> int | None:
    """Return a valid PostgreSQL integer SSE cursor without raising on input."""
    if not value or not value.isascii() or not value.isdecimal() or len(value) > 10:
        return None
    parsed = int(value)
    return parsed if parsed <= MAX_EVENT_SEQUENCE else None


async def append_event(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    event_type: str,
    data: dict,
) -> WorkflowEvent:
    """Append one event while holding the Run row as the sequence authority."""
    locked_run = await session.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run.id).with_for_update()
    )
    if locked_run is None:
        raise LookupError("工作流运行不存在")
    locked_run.event_seq += 1
    locked_run.updated_at = utcnow()
    event = WorkflowEvent(
        tenant_id=locked_run.tenant_id,
        workflow_run_id=locked_run.id,
        sequence=locked_run.event_seq,
        event_type=event_type,
        data=data,
    )
    session.add(locked_run)
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: UUID,
    after_sequence: int,
    limit: int = 100,
) -> list[WorkflowEvent]:
    result = await session.scalars(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.tenant_id == tenant_id,
            WorkflowEvent.workflow_run_id == run_id,
            WorkflowEvent.sequence > after_sequence,
        )
        .order_by(WorkflowEvent.sequence)
        .limit(limit)
    )
    return list(result.all())

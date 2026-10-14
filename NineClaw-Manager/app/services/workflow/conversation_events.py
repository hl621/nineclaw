"""Persistent event helpers for node conversations.

The conversation row is the sequence authority.  This lets an SSE endpoint
resume from ``Last-Event-ID`` without relying on Hermes event retention.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    WorkflowNodeConversation,
    WorkflowNodeConversationEvent,
    utcnow,
)


async def append_conversation_event(
    session: AsyncSession,
    *,
    conversation: WorkflowNodeConversation,
    event_type: str,
    data: dict,
    turn_id: UUID | None = None,
) -> WorkflowNodeConversationEvent:
    """Append one event with a conversation-local, monotonic sequence."""

    locked = await session.scalar(
        select(WorkflowNodeConversation)
        .where(WorkflowNodeConversation.id == conversation.id)
        .with_for_update()
    )
    if locked is None:
        raise LookupError("节点对话不存在")

    locked.event_seq += 1
    locked.updated_at = utcnow()
    event = WorkflowNodeConversationEvent(
        tenant_id=locked.tenant_id,
        conversation_id=locked.id,
        turn_id=turn_id,
        sequence=locked.event_seq,
        event_type=event_type,
        data=dict(data),
    )
    session.add(locked)
    session.add(event)
    await session.flush()
    return event


async def replay_conversation_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    conversation_id: UUID,
    after_sequence: int = 0,
    limit: int = 100,
) -> list[WorkflowNodeConversationEvent]:
    """Return a bounded, tenant-scoped replay slice after one SSE sequence."""

    if after_sequence < 0:
        raise ValueError("事件序号不能小于 0")
    if limit < 1:
        raise ValueError("事件数量必须大于 0")

    conversation = await session.scalar(
        select(WorkflowNodeConversation.id).where(
            WorkflowNodeConversation.id == conversation_id,
            WorkflowNodeConversation.tenant_id == tenant_id,
        )
    )
    if conversation is None:
        raise LookupError("节点对话不存在")

    result = await session.scalars(
        select(WorkflowNodeConversationEvent)
        .where(
            WorkflowNodeConversationEvent.tenant_id == tenant_id,
            WorkflowNodeConversationEvent.conversation_id == conversation_id,
            WorkflowNodeConversationEvent.sequence > after_sequence,
        )
        .order_by(WorkflowNodeConversationEvent.sequence)
        .limit(min(limit, 500))
    )
    return list(result.all())


list_conversation_events = replay_conversation_events

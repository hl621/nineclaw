"""Public API for durable, independent Hermes node conversations."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.routes.workflows import get_tenant_id
from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.workflow import (
    WorkflowNodeConversation,
    WorkflowNodeConversationEvent,
    WorkflowNodeConversationTurn,
)
from app.schemas.workflow import (
    WorkflowApiResponse,
    WorkflowConversationApprovalRequest,
    WorkflowConversationCancelRequest,
    WorkflowConversationCreateRequest,
    WorkflowConversationEventResponse,
    WorkflowConversationResponse,
    WorkflowConversationTurnRequest,
    WorkflowConversationTurnResponse,
    WorkflowResolveFailedRequest,
)
from app.services.workflow.conversation_events import replay_conversation_events
from app.services.workflow.events import MAX_EVENT_SEQUENCE, parse_last_event_id
from app.services.workflow.conversations import (
    ConversationConflictError,
    ConversationNotFoundError,
    ConversationValidationError,
    WorkflowConversationError,
    WorkflowConversationService,
)


router = APIRouter(tags=["workflows"])

_PUBLIC_EVENT_DATA_KEYS = frozenset(
    {"conversation_id", "node_id", "turn_id", "turn_number", "code", "decision"}
)


def _conversation_response(
    conversation: WorkflowNodeConversation,
) -> WorkflowConversationResponse:
    """Return the only conversation fields allowed outside Manager."""

    return WorkflowConversationResponse(
        id=conversation.id,
        workflow_id=conversation.workflow_id,
        node_definition_id=conversation.node_definition_id,
        status=conversation.status,
        attention_reason=_public_attention_reason(conversation),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _turn_response(
    turn: WorkflowNodeConversationTurn,
) -> WorkflowConversationTurnResponse:
    """Project chat content without Hermes run/session or raw error details."""

    return WorkflowConversationTurnResponse(
        id=turn.id,
        conversation_id=turn.conversation_id,
        turn_number=turn.turn_number,
        user_message=_message_projection(turn.user_message, default_role="user"),
        assistant_message=(
            _message_projection(turn.assistant_message, default_role="assistant")
            if turn.assistant_message is not None
            else None
        ),
        status=turn.status,
        error_code=turn.error_code,
        error_message=_public_turn_error_message(turn),
        cancel_requested_at=turn.cancel_requested_at,
        created_at=turn.created_at,
        started_at=turn.started_at,
        finished_at=turn.finished_at,
    )


def _event_response(
    event: WorkflowNodeConversationEvent,
) -> WorkflowConversationEventResponse:
    """Keep future event additions from accidentally exposing internal fields."""

    data = event.data if isinstance(event.data, dict) else {}
    return WorkflowConversationEventResponse(
        sequence=event.sequence,
        event_type=event.event_type,
        data={
            key: value for key, value in data.items() if key in _PUBLIC_EVENT_DATA_KEYS
        },
        created_at=event.created_at,
    )


def _message_projection(
    message: dict[str, Any] | None, *, default_role: str
) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {"role": default_role, "content": ""}
    return {
        "role": default_role,
        "content": _public_message_content(message.get("content")),
    }


def _public_message_content(value: Any) -> str:
    """Expose text only; raw Hermes content may carry tool metadata or secrets."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(value, list):
        texts = [
            item["text"]
            for item in value
            if isinstance(item, dict)
            and item.get("type") in {"text", "output_text"}
            and isinstance(item.get("text"), str)
        ]
        return "\n".join(texts)
    return ""


def _public_attention_reason(conversation: WorkflowNodeConversation) -> str | None:
    if conversation.status == "uncertain":
        return "当前回合执行结果未知，需要人工处置"
    if conversation.status == "approval_required":
        return "当前回合等待审批"
    return None


def _public_turn_error_message(turn: WorkflowNodeConversationTurn) -> str | None:
    if turn.error_code is None:
        return None
    if turn.status == "uncertain":
        return "当前回合执行结果未知，需要人工处置"
    if turn.status == "failed":
        return "当前回合执行失败"
    return None


def _conversation_http_error(exc: WorkflowConversationError) -> HTTPException:
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConversationConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


@router.post(
    "/workflows/{workflow_id}/nodes/{node_id}/conversations",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an independent Hermes node conversation",
)
async def create_workflow_node_conversation(
    workflow_id: UUID,
    node_id: str,
    body: WorkflowConversationCreateRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    """Snapshot the latest published top-level Hermes node into a conversation."""

    del body  # The empty request body reserves future Manager-owned options.
    try:
        conversation = await WorkflowConversationService(session).create_conversation(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            node_definition_id=node_id,
        )
        await session.commit()
        await session.refresh(conversation)
    except WorkflowConversationError as exc:
        await session.rollback()
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(
        data=_conversation_response(conversation).model_dump(mode="json")
    )


@router.post(
    "/workflow-conversations/{conversation_id}/turns",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue one serialized conversation turn",
)
async def start_workflow_conversation_turn(
    conversation_id: UUID,
    body: WorkflowConversationTurnRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message=body.message,
            idempotency_key=idempotency_key,
        )
        await session.commit()
        await session.refresh(turn)
    except WorkflowConversationError as exc:
        await session.rollback()
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(data=_turn_response(turn).model_dump(mode="json"))


@router.get(
    "/workflow-conversations/{conversation_id}",
    response_model=WorkflowApiResponse,
    summary="Get a node conversation",
)
async def get_workflow_conversation(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        conversation = await WorkflowConversationService(session).get_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
    except WorkflowConversationError as exc:
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(
        data=_conversation_response(conversation).model_dump(mode="json")
    )


@router.get(
    "/workflow-conversations/{conversation_id}/turns",
    response_model=WorkflowApiResponse,
    summary="List serialized node-conversation turns",
)
async def list_workflow_conversation_turns(
    conversation_id: UUID,
    after_turn_number: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        turns = await WorkflowConversationService(session).list_turns(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            after_turn_number=after_turn_number,
            limit=limit,
        )
    except WorkflowConversationError as exc:
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(
        data={
            "items": [_turn_response(turn).model_dump(mode="json") for turn in turns],
            "total": len(turns),
            "next_after_turn_number": (
                turns[-1].turn_number if len(turns) == limit else None
            ),
        }
    )


@router.post(
    "/workflow-conversations/{conversation_id}/turns/{turn_id}/cancel",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel a node-conversation turn",
)
async def cancel_workflow_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    body: WorkflowConversationCancelRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    del body
    try:
        turn = await WorkflowConversationService(session).request_cancel(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            requested_by=tenant_id,
        )
        await session.commit()
        await session.refresh(turn)
    except WorkflowConversationError as exc:
        await session.rollback()
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(data=_turn_response(turn).model_dump(mode="json"))


@router.post(
    "/workflow-conversations/{conversation_id}/turns/{turn_id}/mark-failed",
    response_model=WorkflowApiResponse,
    summary="Resolve an uncertain node-conversation turn as failed",
)
async def mark_workflow_conversation_turn_failed(
    conversation_id: UUID,
    turn_id: UUID,
    body: WorkflowResolveFailedRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        turn = await WorkflowConversationService(session).resolve_uncertain_as_failed(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            reason=body.reason,
        )
        await session.commit()
        await session.refresh(turn)
    except WorkflowConversationError as exc:
        await session.rollback()
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(data=_turn_response(turn).model_dump(mode="json"))


@router.post(
    "/workflow-conversations/{conversation_id}/turns/{turn_id}/approval",
    response_model=WorkflowApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Forward a Hermes approval decision",
)
async def approve_workflow_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    body: WorkflowConversationApprovalRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> WorkflowApiResponse:
    try:
        turn = await WorkflowConversationService(session).request_approval(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            decision=body.decision,
            reason=body.reason,
        )
        await session.commit()
        await session.refresh(turn)
    except WorkflowConversationError as exc:
        await session.rollback()
        raise _conversation_http_error(exc) from exc
    return WorkflowApiResponse(data=_turn_response(turn).model_dump(mode="json"))


@router.get(
    "/workflow-conversations/{conversation_id}/events/stream",
    summary="Replay node-conversation lifecycle events over SSE",
)
async def stream_workflow_conversation_events(
    conversation_id: UUID,
    request: Request,
    after_sequence: int = Query(default=0, ge=0, le=MAX_EVENT_SEQUENCE),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> EventSourceResponse:
    try:
        await WorkflowConversationService(session).get_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
    except WorkflowConversationError as exc:
        raise _conversation_http_error(exc) from exc

    header_sequence = parse_last_event_id(request.headers.get("Last-Event-ID"))
    if header_sequence is not None:
        after_sequence = max(after_sequence, header_sequence)

    # The SSE generator owns fresh, short-lived sessions. Release the request
    # session before returning so an open conversation stream holds no DB pool
    # connection between polls.
    await session.rollback()

    async def event_generator():
        sequence = after_sequence
        while not await request.is_disconnected():
            async with async_session_maker() as event_session:
                events = await replay_conversation_events(
                    event_session,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    after_sequence=sequence,
                    limit=100,
                )
            for event in events:
                projection = _event_response(event)
                sequence = projection.sequence
                yield {
                    "id": str(projection.sequence),
                    "event": projection.event_type,
                    "data": json.dumps(
                        projection.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                }
            if len(events) == 100:
                continue
            await asyncio.sleep(settings.workflow_scheduler_poll_seconds)

    return EventSourceResponse(
        event_generator(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        ping=15,
    )

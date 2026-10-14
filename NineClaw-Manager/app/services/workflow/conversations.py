"""Durable service layer for independent Hermes node conversations.

This module owns persisted state transitions.  It deliberately contains no
HTTP or FastAPI objects, so routes can own authentication and transaction
boundaries while the scheduler owns external Hermes calls.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.instance import ServiceInstance
from app.models.workflow import (
    Workflow,
    WorkflowNodeConversation,
    WorkflowNodeConversationJob,
    WorkflowNodeConversationTurn,
    WorkflowVersion,
    utcnow,
)
from app.services.workflow.conversation_events import append_conversation_event
from app.services.workflow.compiler import (
    WorkflowCompilationError,
    ensure_workflow_dsl_v2,
)


TURN_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
TURN_BLOCKING_STATUSES = frozenset(
    {
        "queued",
        "dispatching",
        "running",
        "approval_required",
        "approval_submitting",
        "cancel_requested",
        "uncertain",
    }
)
_REMOTE_ACTIVE_STATUSES = frozenset(
    {"queued", "running", "pending", "in_progress", "waiting", ""}
)
_REMOTE_SUCCESS_STATUSES = frozenset({"succeeded", "success", "completed", "done"})
_REMOTE_CANCELLED_STATUSES = frozenset({"cancelled", "canceled", "stopped"})
_REMOTE_FAILED_STATUSES = frozenset({"failed", "error", "rejected", "expired"})
_REMOTE_APPROVAL_STATUSES = frozenset({"requires_action", "waiting_approval"})


class WorkflowConversationError(RuntimeError):
    """Base error for node conversation domain failures."""


class ConversationNotFoundError(WorkflowConversationError):
    pass


class ConversationValidationError(WorkflowConversationError):
    pass


class ConversationConflictError(WorkflowConversationError):
    pass


@dataclass(frozen=True)
class ConversationDispatch:
    job_id: UUID
    fencing_token: int
    tenant_id: str
    conversation_id: UUID
    turn_id: UUID
    base_url: str
    api_key: str
    model: str
    messages: list[dict[str, Any]]
    instructions: str | None
    session_id: str
    extra: dict[str, Any]


@dataclass(frozen=True)
class ConversationMonitor:
    job_id: UUID
    fencing_token: int
    tenant_id: str
    conversation_id: UUID
    turn_id: UUID
    base_url: str
    api_key: str
    external_run_id: str


@dataclass(frozen=True)
class ConversationAction:
    job_id: UUID
    fencing_token: int
    tenant_id: str
    conversation_id: UUID
    turn_id: UUID
    base_url: str
    api_key: str
    external_run_id: str
    decision: str | None = None
    reason: str | None = None


class WorkflowConversationService:
    """State machine and read API for independent Agent-node conversations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        workflow_id: UUID,
        node_definition_id: str,
    ) -> WorkflowNodeConversation:
        """Snapshot the current published top-level Hermes node into a conversation."""

        workflow = await self.session.scalar(
            select(Workflow)
            .where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
            .with_for_update()
        )
        if workflow is None:
            raise ConversationNotFoundError("工作流不存在")
        if workflow.current_version_number is None:
            raise ConversationValidationError("工作流尚未发布")

        version = await self.session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.tenant_id == tenant_id,
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version_number == workflow.current_version_number,
            )
        )
        if version is None:
            raise ConversationValidationError("当前发布版本不存在")
        try:
            ensure_workflow_dsl_v2(version.definition)
        except WorkflowCompilationError as exc:
            raise ConversationValidationError(
                "WORKFLOW_DSL_V1_UNSUPPORTED: 当前发布版本不支持"
            ) from exc

        node = _top_level_hermes_node(version.compiled_plan, node_definition_id)
        config = node.get("config")
        if not isinstance(config, dict):
            raise ConversationValidationError("智能体节点配置无效")
        instance_id = config.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ConversationValidationError("智能体节点缺少 instance_id")

        instance = await self.session.scalar(
            select(ServiceInstance).where(
                ServiceInstance.id == instance_id,
                ServiceInstance.tenant_id == tenant_id,
            )
        )
        if instance is None:
            raise ConversationValidationError("智能体实例不存在或不属于当前租户")

        conversation_id = uuid4()
        conversation = WorkflowNodeConversation(
            id=conversation_id,
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            node_definition_id=node_definition_id,
            instance_id=instance.id,
            remote_session_id=f"wfconv-{conversation_id.hex}",
            node_snapshot=deepcopy(node),
        )
        self.session.add(conversation)
        await self.session.flush()
        await append_conversation_event(
            self.session,
            conversation=conversation,
            event_type="conversation.created",
            data={
                "conversation_id": str(conversation.id),
                "node_id": conversation.node_definition_id,
            },
        )
        return conversation

    async def start_turn(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        message: str,
        idempotency_key: str | None = None,
    ) -> WorkflowNodeConversationTurn:
        """Persist one user message and enqueue exactly one Hermes create call."""

        if not isinstance(message, str) or not message.strip():
            raise ConversationValidationError("消息不能为空")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise ConversationValidationError("Idempotency-Key 不能为空")
            idempotency_key = idempotency_key.strip()
            if len(idempotency_key) > 128:
                raise ConversationValidationError("Idempotency-Key 不能超过 128 个字符")

        conversation = await self._locked_conversation(tenant_id, conversation_id)
        await self._require_conversation_dsl_v2(conversation)
        if idempotency_key is not None:
            existing = await self.session.scalar(
                select(WorkflowNodeConversationTurn)
                .where(
                    WorkflowNodeConversationTurn.conversation_id == conversation.id,
                    WorkflowNodeConversationTurn.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if existing is not None:
                existing_message = (
                    existing.user_message.get("content")
                    if isinstance(existing.user_message, dict)
                    else None
                )
                if existing_message != message:
                    raise ConversationConflictError(
                        "Idempotency-Key 已用于内容不同的对话回合"
                    )
                return existing
        blocker = await self.session.scalar(
            select(WorkflowNodeConversationTurn)
            .where(
                WorkflowNodeConversationTurn.conversation_id == conversation.id,
                WorkflowNodeConversationTurn.status.in_(TURN_BLOCKING_STATUSES),
            )
            .order_by(WorkflowNodeConversationTurn.turn_number.desc())
            .with_for_update()
            .limit(1)
        )
        if blocker is not None or conversation.status == "uncertain":
            raise ConversationConflictError("上一回合尚未结束或需要人工处置")

        last_number = int(
            await self.session.scalar(
                select(
                    func.coalesce(func.max(WorkflowNodeConversationTurn.turn_number), 0)
                ).where(WorkflowNodeConversationTurn.conversation_id == conversation.id)
            )
            or 0
        )
        turn = WorkflowNodeConversationTurn(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            turn_number=last_number + 1,
            executor_instance_id=conversation.instance_id,
            user_message={"role": "user", "content": message},
            idempotency_key=idempotency_key,
        )
        conversation.status = "queued"
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        self.session.add(turn)
        self.session.add(conversation)
        await self.session.flush()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="dispatch_turn",
            dedupe_key=f"dispatch:{turn.id}",
            payload={},
            allow_requeue=False,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.queued",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        return turn

    async def request_cancel(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        turn_id: UUID,
        requested_by: str | None = None,
    ) -> WorkflowNodeConversationTurn:
        """Request cancellation without retrying an unconfirmed remote stop."""

        conversation = await self._locked_conversation(tenant_id, conversation_id)
        turn = await self._locked_turn(conversation, turn_id)
        if turn.status in TURN_TERMINAL_STATUSES:
            return turn
        if turn.status == "uncertain":
            raise ConversationConflictError("当前回合结果未知，需要人工处置")
        if turn.status == "cancel_requested":
            return turn

        if turn.status == "queued":
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="cancelled",
                error_code=None,
                error_message=None,
            )
            await self._finish_queued_dispatch_job(turn)
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.cancelled",
                data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
            )
            return turn

        turn.status = "cancel_requested"
        turn.cancel_requested_at = utcnow()
        turn.cancel_requested_by = (
            requested_by[:128] if isinstance(requested_by, str) else None
        )
        turn.updated_at = utcnow()
        conversation.status = "cancel_requested"
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        if turn.external_run_id is not None:
            await self._enqueue_job(
                conversation=conversation,
                turn=turn,
                job_type="cancel_turn",
                dedupe_key=f"cancel:{turn.id}",
                payload={},
                allow_requeue=True,
            )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.cancel_requested",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        return turn

    async def resolve_uncertain_as_failed(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        turn_id: UUID,
        reason: str,
    ) -> WorkflowNodeConversationTurn:
        """Record an operator's terminal decision without invoking Hermes."""

        if not isinstance(reason, str) or not reason.strip():
            raise ConversationValidationError("人工处置原因不能为空")
        conversation = await self._locked_conversation(tenant_id, conversation_id)
        await self._require_conversation_dsl_v2(conversation)
        turn = await self._locked_turn(conversation, turn_id)
        if turn.status != "uncertain":
            raise ConversationConflictError("当前回合不需要人工处置")
        self._set_turn_terminal(
            conversation=conversation,
            turn=turn,
            status="failed",
            error_code="MANUAL_UNCERTAIN_RESOLVED",
            error_message=reason.strip(),
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.failed",
            data={"turn_id": str(turn.id), "code": "MANUAL_UNCERTAIN_RESOLVED"},
        )
        return turn

    async def request_approval(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        turn_id: UUID,
        decision: str,
        reason: str | None = None,
    ) -> WorkflowNodeConversationTurn:
        """Persist a user-approved Hermes decision for asynchronous forwarding."""

        if decision not in {"allow", "deny"}:
            raise ConversationValidationError("审批决定必须为 allow 或 deny")

        conversation = await self._locked_conversation(tenant_id, conversation_id)
        await self._require_conversation_dsl_v2(conversation)
        turn = await self._locked_turn(conversation, turn_id)
        if turn.status != "approval_required" or turn.external_run_id is None:
            raise ConversationConflictError("当前回合未等待 Hermes 审批")

        turn.status = "approval_submitting"
        turn.error_code = None
        turn.error_message = None
        turn.updated_at = utcnow()
        conversation.status = "approval_submitting"
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="approve_turn",
            dedupe_key=f"approval:{turn.id}",
            payload={"decision": decision, "reason": reason or ""},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.approval_submitting",
            data={
                "turn_id": str(turn.id),
                "turn_number": turn.turn_number,
                "decision": decision,
            },
        )
        return turn

    async def get_conversation(
        self, *, tenant_id: str, conversation_id: UUID
    ) -> WorkflowNodeConversation:
        conversation = await self.session.scalar(
            select(WorkflowNodeConversation).where(
                WorkflowNodeConversation.id == conversation_id,
                WorkflowNodeConversation.tenant_id == tenant_id,
            )
        )
        if conversation is None:
            raise ConversationNotFoundError("节点对话不存在")
        return conversation

    async def get_turn(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        turn_id: UUID,
    ) -> WorkflowNodeConversationTurn:
        await self.get_conversation(
            tenant_id=tenant_id, conversation_id=conversation_id
        )
        turn = await self.session.scalar(
            select(WorkflowNodeConversationTurn).where(
                WorkflowNodeConversationTurn.id == turn_id,
                WorkflowNodeConversationTurn.conversation_id == conversation_id,
                WorkflowNodeConversationTurn.tenant_id == tenant_id,
            )
        )
        if turn is None:
            raise ConversationNotFoundError("对话回合不存在")
        return turn

    async def list_turns(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        after_turn_number: int = 0,
        limit: int = 100,
    ) -> list[WorkflowNodeConversationTurn]:
        if after_turn_number < 0:
            raise ConversationValidationError("回合序号不能小于 0")
        if limit < 1:
            raise ConversationValidationError("回合数量必须大于 0")
        await self.get_conversation(
            tenant_id=tenant_id, conversation_id=conversation_id
        )
        result = await self.session.scalars(
            select(WorkflowNodeConversationTurn)
            .where(
                WorkflowNodeConversationTurn.tenant_id == tenant_id,
                WorkflowNodeConversationTurn.conversation_id == conversation_id,
                WorkflowNodeConversationTurn.turn_number > after_turn_number,
            )
            .order_by(WorkflowNodeConversationTurn.turn_number)
            .limit(min(limit, 500))
        )
        return list(result.all())

    async def prepare_dispatch(
        self,
        *,
        job: WorkflowNodeConversationJob,
        fencing_token: int,
        reclaimed: bool = False,
    ) -> ConversationDispatch | None:
        """Move a queued turn to dispatching before the scheduler calls Hermes."""

        conversation, turn, locked_job = await self._locked_job_context(job.id)
        if locked_job.fencing_token != fencing_token or locked_job.status != "running":
            return None
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=locked_job,
            )
            return None
        if (
            reclaimed
            and turn.external_run_id is None
            and turn.status in {"dispatching", "cancel_requested"}
        ):
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_CREATE_UNCERTAIN",
                message="Hermes 创建任务租约过期，无法确认远端是否已创建 Run",
            )
            return None
        if turn.status != "queued" or turn.external_run_id is not None:
            await self._finish_job(locked_job)
            return None

        instance = await self.session.scalar(
            select(ServiceInstance).where(
                ServiceInstance.id == conversation.instance_id,
                ServiceInstance.tenant_id == conversation.tenant_id,
            )
        )
        if instance is None or instance.actual_state != "running":
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="failed",
                error_code="HERMES_INSTANCE_UNAVAILABLE",
                error_message="Hermes 实例不存在或未运行",
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.failed",
                data={
                    "turn_id": str(turn.id),
                    "code": "HERMES_INSTANCE_UNAVAILABLE",
                },
            )
            await self._finish_job(locked_job, status="failed")
            return None

        turn.status = "dispatching"
        turn.updated_at = utcnow()
        conversation.status = "dispatching"
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.dispatching",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        config = _node_config(conversation)
        return ConversationDispatch(
            job_id=locked_job.id,
            fencing_token=fencing_token,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            base_url=self._gateway_base_url(conversation.instance_id),
            api_key=settings.nineclaw_token,
            model=str(config.get("model") or "hermes-agent"),
            messages=_build_turn_messages(config, turn),
            instructions=_build_conversation_instructions(config),
            session_id=conversation.remote_session_id,
            extra={
                key: value
                for key, value in config.items()
                if key in {"temperature", "max_tokens"}
            },
        )

    async def persist_dispatched(
        self, *, dispatch: ConversationDispatch, external_run_id: str
    ) -> None:
        """Record a confirmed Hermes Run and schedule monitoring exactly once."""

        conversation, turn, job = await self._locked_job_context(dispatch.job_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if turn.id != dispatch.turn_id or turn.status not in {
            "dispatching",
            "cancel_requested",
        }:
            await self._finish_job(job)
            return
        if turn.external_run_id is not None:
            await self._finish_job(job)
            return

        duplicate = await self.session.scalar(
            select(WorkflowNodeConversationTurn.id).where(
                WorkflowNodeConversationTurn.tenant_id == conversation.tenant_id,
                WorkflowNodeConversationTurn.executor_instance_id
                == turn.executor_instance_id,
                WorkflowNodeConversationTurn.external_run_id == external_run_id,
                WorkflowNodeConversationTurn.id != turn.id,
            )
        )
        if duplicate is not None:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=job,
                code="HERMES_RUN_ID_CONFLICT",
                message="Hermes run_id 已关联到其他对话回合",
            )
            return

        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=job,
                external_run_id=external_run_id,
            )
            return

        cancellation_requested = turn.status == "cancel_requested"
        turn.external_run_id = external_run_id
        turn.status = "cancel_requested" if cancellation_requested else "running"
        turn.started_at = turn.started_at or utcnow()
        turn.updated_at = utcnow()
        conversation.status = (
            "cancel_requested" if cancellation_requested else "running"
        )
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="monitor_turn",
            dedupe_key=f"monitor:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.started",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        if cancellation_requested:
            await self._enqueue_job(
                conversation=conversation,
                turn=turn,
                job_type="cancel_turn",
                dedupe_key=f"cancel:{turn.id}",
                payload={},
                allow_requeue=True,
            )
        await self._finish_job(job)

    async def persist_dispatch_rejected(
        self, *, dispatch: ConversationDispatch, error: str
    ) -> None:
        """Persist a confirmed pre-create rejection without retrying the turn."""

        conversation, turn, job = await self._locked_job_context(dispatch.job_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if turn.id != dispatch.turn_id or turn.external_run_id is not None:
            await self._finish_job(job)
            return
        status = "cancelled" if turn.status == "cancel_requested" else "failed"
        code = None if status == "cancelled" else "HERMES_CREATE_REJECTED"
        message = None if status == "cancelled" else error
        self._set_turn_terminal(
            conversation=conversation,
            turn=turn,
            status=status,
            error_code=code,
            error_message=message,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.cancelled" if status == "cancelled" else "turn.failed",
            data=(
                {"turn_id": str(turn.id), "code": code}
                if code
                else {"turn_id": str(turn.id)}
            ),
        )
        await self._finish_job(job, status="failed")

    async def persist_dispatch_uncertain(
        self, *, dispatch: ConversationDispatch, error: str
    ) -> None:
        """Freeze a turn when Hermes may have accepted the create request."""

        conversation, turn, job = await self._locked_job_context(dispatch.job_id)
        if job.status != "running" or job.fencing_token != dispatch.fencing_token:
            return
        if turn.id == dispatch.turn_id and turn.external_run_id is None:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=job,
                code="HERMES_CREATE_UNCERTAIN",
                message=error,
            )
            return
        await self._finish_job(job)

    async def prepare_monitor(
        self,
        *,
        job: WorkflowNodeConversationJob,
        fencing_token: int,
    ) -> ConversationMonitor | None:
        """Prepare a read-only Hermes status request for one known external Run."""

        conversation, turn, locked_job = await self._locked_job_context(job.id)
        if locked_job.fencing_token != fencing_token or locked_job.status != "running":
            return None
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=locked_job,
            )
            return None
        if turn.external_run_id is None:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_MONITOR_MISSING_RUN_ID",
                message="监控任务缺少 Hermes run_id",
            )
            return None
        if turn.status not in {"running", "cancel_requested", "approval_required"}:
            await self._finish_job(locked_job)
            return None
        return ConversationMonitor(
            job_id=locked_job.id,
            fencing_token=fencing_token,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            base_url=self._gateway_base_url(conversation.instance_id),
            api_key=settings.nineclaw_token,
            external_run_id=turn.external_run_id,
        )

    async def persist_monitor_result(
        self, *, monitor: ConversationMonitor, payload: dict[str, Any]
    ) -> None:
        """Persist an observed remote status; monitoring itself may be retried."""

        conversation, turn, job = await self._locked_job_context(monitor.job_id)
        if job.status != "running" or job.fencing_token != monitor.fencing_token:
            return
        if (
            turn.id != monitor.turn_id
            or turn.external_run_id != monitor.external_run_id
            or turn.status not in {"running", "cancel_requested", "approval_required"}
        ):
            await self._finish_job(job)
            return

        remote_status = _remote_status(payload)
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=job,
                remote_is_terminal=(
                    remote_status
                    in (
                        _REMOTE_SUCCESS_STATUSES
                        | _REMOTE_CANCELLED_STATUSES
                        | _REMOTE_FAILED_STATUSES
                    )
                ),
            )
            return
        if remote_status in _REMOTE_APPROVAL_STATUSES:
            if turn.status == "cancel_requested":
                await self._enqueue_job(
                    conversation=conversation,
                    turn=turn,
                    job_type="cancel_turn",
                    dedupe_key=f"cancel:{turn.id}",
                    payload={},
                    allow_requeue=True,
                )
                await self._finish_job(job)
                return
            turn.status = "approval_required"
            turn.updated_at = utcnow()
            conversation.status = "approval_required"
            conversation.attention_reason = "Hermes Run 等待审批"
            conversation.updated_at = utcnow()
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.approval_required",
                data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
            )
            await self._finish_job(job)
            return
        if remote_status in _REMOTE_ACTIVE_STATUSES:
            await self._requeue_monitor_job(job)
            return
        if remote_status in _REMOTE_SUCCESS_STATUSES:
            turn.assistant_message = _extract_assistant_message(payload)
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="succeeded",
                error_code=None,
                error_message=None,
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.completed",
                data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
            )
        elif remote_status in _REMOTE_CANCELLED_STATUSES:
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="cancelled",
                error_code=None,
                error_message=None,
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.cancelled",
                data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
            )
        elif remote_status in _REMOTE_FAILED_STATUSES:
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="failed",
                error_code="HERMES_RUN_FAILED",
                error_message=_extract_remote_error(payload),
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.failed",
                data={"turn_id": str(turn.id), "code": "HERMES_RUN_FAILED"},
            )
        else:
            await self._requeue_monitor_job(job)
            return
        await self._finish_job(job)

    async def release_monitor_after_error(
        self, *, monitor: ConversationMonitor
    ) -> None:
        """Retry only monitoring after a transient read failure."""

        conversation, turn, job = await self._locked_job_context(monitor.job_id)
        if job.status == "running" and job.fencing_token == monitor.fencing_token:
            if not await self._conversation_uses_dsl_v2(conversation):
                await self._quarantine_unsupported_v1_turn(
                    conversation=conversation,
                    turn=turn,
                    job=job,
                )
                return
            await self._requeue_monitor_job(job)

    async def prepare_cancel(
        self,
        *,
        job: WorkflowNodeConversationJob,
        fencing_token: int,
        reclaimed: bool = False,
    ) -> ConversationAction | None:
        conversation, turn, locked_job = await self._locked_job_context(job.id)
        if locked_job.fencing_token != fencing_token or locked_job.status != "running":
            return None
        if turn.status != "cancel_requested":
            await self._finish_job(locked_job)
            return None
        if turn.external_run_id is None:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_CANCEL_MISSING_RUN_ID",
                message="取消任务缺少 Hermes run_id",
            )
            return None
        if reclaimed:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_CANCEL_UNCERTAIN",
                message="Hermes 取消任务租约过期，无法确认停止请求是否已送达",
            )
            return None
        return ConversationAction(
            job_id=locked_job.id,
            fencing_token=fencing_token,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            base_url=self._gateway_base_url(conversation.instance_id),
            api_key=settings.nineclaw_token,
            external_run_id=turn.external_run_id,
        )

    async def persist_cancel_accepted(self, *, action: ConversationAction) -> None:
        conversation, turn, job = await self._locked_job_context(action.job_id)
        if job.status != "running" or job.fencing_token != action.fencing_token:
            return
        if (
            turn.status != "cancel_requested"
            or turn.external_run_id != action.external_run_id
        ):
            await self._finish_job(job)
            return
        if not await self._conversation_uses_dsl_v2(conversation):
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="failed",
                error_code="WORKFLOW_DSL_V1_UNSUPPORTED",
                error_message="DSL v1 已停用，已请求停止历史 Hermes Run",
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.failed",
                data={
                    "turn_id": str(turn.id),
                    "code": "WORKFLOW_DSL_V1_UNSUPPORTED",
                },
            )
            await self._finish_job(job)
            return
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="monitor_turn",
            dedupe_key=f"monitor:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.cancel_acknowledged",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        await self._finish_job(job)

    async def persist_cancel_rejected(
        self, *, action: ConversationAction, error: str
    ) -> None:
        conversation, turn, job = await self._locked_job_context(action.job_id)
        if job.status != "running" or job.fencing_token != action.fencing_token:
            return
        if (
            turn.status != "cancel_requested"
            or turn.external_run_id != action.external_run_id
        ):
            await self._finish_job(job)
            return
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=job,
                code="WORKFLOW_DSL_V1_STOP_UNCONFIRMED",
                message=("DSL v1 已停用，历史 Hermes Run 停止请求被拒绝：" f"{error}"),
            )
            return
        turn.error_code = "HERMES_CANCEL_REJECTED"
        turn.error_message = error[:2048]
        turn.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="monitor_turn",
            dedupe_key=f"monitor:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.cancel_rejected",
            data={"turn_id": str(turn.id)},
        )
        await self._finish_job(job, status="failed")

    async def prepare_approval(
        self,
        *,
        job: WorkflowNodeConversationJob,
        fencing_token: int,
        reclaimed: bool = False,
    ) -> ConversationAction | None:
        conversation, turn, locked_job = await self._locked_job_context(job.id)
        if locked_job.fencing_token != fencing_token or locked_job.status != "running":
            return None
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=locked_job,
            )
            return None
        if turn.status != "approval_submitting" or turn.external_run_id is None:
            await self._finish_job(locked_job)
            return None
        if reclaimed:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_APPROVAL_UNCERTAIN",
                message="Hermes 审批任务租约过期，无法确认审批决定是否已送达",
            )
            return None
        decision = locked_job.payload.get("decision")
        if decision not in {"allow", "deny"}:
            await self._mark_uncertain(
                conversation=conversation,
                turn=turn,
                job=locked_job,
                code="HERMES_APPROVAL_PAYLOAD_INVALID",
                message="审批任务载荷无效",
            )
            return None
        reason = locked_job.payload.get("reason")
        return ConversationAction(
            job_id=locked_job.id,
            fencing_token=fencing_token,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            base_url=self._gateway_base_url(conversation.instance_id),
            api_key=settings.nineclaw_token,
            external_run_id=turn.external_run_id,
            decision=decision,
            reason=reason if isinstance(reason, str) and reason else None,
        )

    async def persist_approval_accepted(self, *, action: ConversationAction) -> None:
        conversation, turn, job = await self._locked_job_context(action.job_id)
        if job.status != "running" or job.fencing_token != action.fencing_token:
            return
        if turn.external_run_id != action.external_run_id or turn.status not in {
            "approval_submitting",
            "cancel_requested",
        }:
            await self._finish_job(job)
            return
        if not await self._conversation_uses_dsl_v2(conversation):
            await self._quarantine_unsupported_v1_turn(
                conversation=conversation,
                turn=turn,
                job=job,
            )
            return
        cancellation_requested = turn.status == "cancel_requested"
        turn.status = "cancel_requested" if cancellation_requested else "running"
        turn.updated_at = utcnow()
        conversation.status = (
            "cancel_requested" if cancellation_requested else "running"
        )
        conversation.attention_reason = None
        conversation.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="monitor_turn",
            dedupe_key=f"monitor:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        if cancellation_requested:
            await self._enqueue_job(
                conversation=conversation,
                turn=turn,
                job_type="cancel_turn",
                dedupe_key=f"cancel:{turn.id}",
                payload={},
                allow_requeue=True,
            )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.approval_submitted",
            data={"turn_id": str(turn.id), "turn_number": turn.turn_number},
        )
        await self._finish_job(job)

    async def persist_approval_rejected(
        self, *, action: ConversationAction, error: str
    ) -> None:
        conversation, turn, job = await self._locked_job_context(action.job_id)
        if job.status != "running" or job.fencing_token != action.fencing_token:
            return
        if (
            turn.external_run_id != action.external_run_id
            or turn.status != "approval_submitting"
        ):
            await self._finish_job(job)
            return
        turn.status = "approval_required"
        turn.error_code = "HERMES_APPROVAL_REJECTED"
        turn.error_message = error[:2048]
        turn.updated_at = utcnow()
        conversation.status = "approval_required"
        conversation.attention_reason = "Hermes 审批请求被拒绝"
        conversation.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="monitor_turn",
            dedupe_key=f"monitor:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.approval_rejected",
            data={"turn_id": str(turn.id)},
        )
        await self._finish_job(job, status="failed")

    async def persist_action_uncertain(
        self, *, action: ConversationAction, action_name: str, error: str
    ) -> None:
        """Freeze side-effecting cancellation/approval calls with unknown result."""

        conversation, turn, job = await self._locked_job_context(action.job_id)
        if job.status != "running" or job.fencing_token != action.fencing_token:
            return
        if turn.external_run_id != action.external_run_id:
            await self._finish_job(job)
            return
        await self._mark_uncertain(
            conversation=conversation,
            turn=turn,
            job=job,
            code=f"HERMES_{action_name.upper()}_UNCERTAIN",
            message=error,
        )

    async def persist_internal_job_error(
        self, *, job_id: UUID, fencing_token: int, error: str
    ) -> None:
        """Conservatively freeze a side-effecting Job after an internal failure."""

        conversation, turn, job = await self._locked_job_context(job_id)
        if job.status != "running" or job.fencing_token != fencing_token:
            return
        if job.job_type == "monitor_turn":
            await self._requeue_monitor_job(job)
            return
        await self._mark_uncertain(
            conversation=conversation,
            turn=turn,
            job=job,
            code="CONVERSATION_JOB_INTERNAL_ERROR",
            message=error,
        )

    async def _require_conversation_dsl_v2(
        self, conversation: WorkflowNodeConversation
    ) -> None:
        if not await self._conversation_uses_dsl_v2(conversation):
            raise ConversationValidationError(
                "WORKFLOW_DSL_V1_UNSUPPORTED: 对话关联的发布版本已停用"
            )

    async def _conversation_uses_dsl_v2(
        self, conversation: WorkflowNodeConversation
    ) -> bool:
        """Read the immutable snapshot before any Hermes-facing operation."""

        version = await self.session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.id == conversation.workflow_version_id,
                WorkflowVersion.tenant_id == conversation.tenant_id,
                WorkflowVersion.workflow_id == conversation.workflow_id,
            )
        )
        if version is None:
            return False
        try:
            ensure_workflow_dsl_v2(version.definition)
        except WorkflowCompilationError:
            return False
        return True

    async def _quarantine_unsupported_v1_turn(
        self,
        *,
        conversation: WorkflowNodeConversation,
        turn: WorkflowNodeConversationTurn,
        job: WorkflowNodeConversationJob,
        external_run_id: str | None = None,
        remote_is_terminal: bool = False,
    ) -> None:
        """Prevent legacy turns from resuming while stopping known remote Runs."""

        if external_run_id:
            turn.external_run_id = external_run_id
            turn.started_at = turn.started_at or utcnow()

        if remote_is_terminal or turn.external_run_id is None:
            if (
                turn.status in {"dispatching", "cancel_requested"}
                and not remote_is_terminal
            ):
                await self._mark_uncertain(
                    conversation=conversation,
                    turn=turn,
                    job=job,
                    code="WORKFLOW_DSL_V1_UNSUPPORTED",
                    message="DSL v1 已停用，无法确认历史 Hermes Run 是否已创建",
                )
                return
            self._set_turn_terminal(
                conversation=conversation,
                turn=turn,
                status="failed",
                error_code="WORKFLOW_DSL_V1_UNSUPPORTED",
                error_message="DSL v1 已停用",
            )
            await append_conversation_event(
                self.session,
                conversation=conversation,
                turn_id=turn.id,
                event_type="turn.failed",
                data={
                    "turn_id": str(turn.id),
                    "code": "WORKFLOW_DSL_V1_UNSUPPORTED",
                },
            )
            await self._finish_job(job, status="failed")
            return

        turn.status = "cancel_requested"
        turn.error_code = "WORKFLOW_DSL_V1_UNSUPPORTED"
        turn.error_message = "DSL v1 已停用，正在停止历史 Hermes Run"
        turn.cancel_requested_at = turn.cancel_requested_at or utcnow()
        turn.updated_at = utcnow()
        conversation.status = "cancel_requested"
        conversation.attention_reason = "WORKFLOW_DSL_V1_UNSUPPORTED"
        conversation.updated_at = utcnow()
        await self._enqueue_job(
            conversation=conversation,
            turn=turn,
            job_type="cancel_turn",
            dedupe_key=f"cancel:{turn.id}",
            payload={},
            allow_requeue=True,
        )
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.cancel_requested",
            data={
                "turn_id": str(turn.id),
                "turn_number": turn.turn_number,
                "code": "WORKFLOW_DSL_V1_UNSUPPORTED",
            },
        )
        await self._finish_job(job, status="failed")

    async def _locked_conversation(
        self, tenant_id: str, conversation_id: UUID
    ) -> WorkflowNodeConversation:
        conversation = await self.session.scalar(
            select(WorkflowNodeConversation)
            .where(
                WorkflowNodeConversation.id == conversation_id,
                WorkflowNodeConversation.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if conversation is None:
            raise ConversationNotFoundError("节点对话不存在")
        return conversation

    async def _locked_turn(
        self, conversation: WorkflowNodeConversation, turn_id: UUID
    ) -> WorkflowNodeConversationTurn:
        turn = await self.session.scalar(
            select(WorkflowNodeConversationTurn)
            .where(
                WorkflowNodeConversationTurn.id == turn_id,
                WorkflowNodeConversationTurn.conversation_id == conversation.id,
                WorkflowNodeConversationTurn.tenant_id == conversation.tenant_id,
            )
            .with_for_update()
        )
        if turn is None:
            raise ConversationNotFoundError("对话回合不存在")
        return turn

    async def _locked_job_context(self, job_id: UUID) -> tuple[
        WorkflowNodeConversation,
        WorkflowNodeConversationTurn,
        WorkflowNodeConversationJob,
    ]:
        hint = await self.session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.id == job_id
            )
        )
        if hint is None:
            raise ConversationNotFoundError("对话 Job 不存在")
        conversation = await self._locked_conversation(
            hint.tenant_id, hint.conversation_id
        )
        job = await self.session.scalar(
            select(WorkflowNodeConversationJob)
            .where(WorkflowNodeConversationJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.tenant_id != conversation.tenant_id:
            raise ConversationNotFoundError("对话 Job 不存在")
        turn = await self._locked_turn(conversation, job.turn_id)
        return conversation, turn, job

    async def _enqueue_job(
        self,
        *,
        conversation: WorkflowNodeConversation,
        turn: WorkflowNodeConversationTurn,
        job_type: str,
        dedupe_key: str,
        payload: dict,
        allow_requeue: bool,
    ) -> WorkflowNodeConversationJob:
        existing = await self.session.scalar(
            select(WorkflowNodeConversationJob)
            .where(
                WorkflowNodeConversationJob.tenant_id == conversation.tenant_id,
                WorkflowNodeConversationJob.dedupe_key == dedupe_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.status in {"queued", "running"}:
                return existing
            if not allow_requeue:
                return existing
            existing.status = "queued"
            existing.payload = dict(payload)
            existing.available_at = utcnow()
            existing.lease_owner = None
            existing.lease_expires_at = None
            existing.error_message = None
            existing.updated_at = utcnow()
            self.session.add(existing)
            await self.session.flush()
            return existing

        job = WorkflowNodeConversationJob(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            job_type=job_type,
            dedupe_key=dedupe_key,
            payload=dict(payload),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def _finish_queued_dispatch_job(
        self, turn: WorkflowNodeConversationTurn
    ) -> None:
        job = await self.session.scalar(
            select(WorkflowNodeConversationJob)
            .where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "dispatch_turn",
                WorkflowNodeConversationJob.status == "queued",
            )
            .with_for_update()
        )
        if job is not None:
            await self._finish_job(job, status="succeeded")

    async def _finish_job(
        self, job: WorkflowNodeConversationJob, *, status: str = "succeeded"
    ) -> None:
        job.status = status
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utcnow()
        self.session.add(job)

    async def _requeue_monitor_job(self, job: WorkflowNodeConversationJob) -> None:
        job.status = "queued"
        job.available_at = utcnow() + timedelta(
            seconds=settings.workflow_monitor_poll_seconds
        )
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utcnow()
        self.session.add(job)

    async def _mark_uncertain(
        self,
        *,
        conversation: WorkflowNodeConversation,
        turn: WorkflowNodeConversationTurn,
        job: WorkflowNodeConversationJob,
        code: str,
        message: str,
    ) -> None:
        turn.status = "uncertain"
        turn.error_code = code[:128]
        turn.error_message = message[:2048]
        turn.finished_at = utcnow()
        turn.updated_at = utcnow()
        conversation.status = "uncertain"
        conversation.attention_reason = message[:2048]
        conversation.updated_at = utcnow()
        await append_conversation_event(
            self.session,
            conversation=conversation,
            turn_id=turn.id,
            event_type="turn.uncertain",
            data={"turn_id": str(turn.id), "code": code[:128]},
        )
        await self._finish_job(job, status="uncertain")

    @staticmethod
    def _set_turn_terminal(
        *,
        conversation: WorkflowNodeConversation,
        turn: WorkflowNodeConversationTurn,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        turn.status = status
        turn.error_code = error_code
        turn.error_message = error_message[:2048] if error_message else None
        turn.finished_at = utcnow()
        turn.updated_at = utcnow()
        conversation.status = "idle"
        conversation.attention_reason = None
        conversation.updated_at = utcnow()

    @staticmethod
    def _gateway_base_url(instance_id: str) -> str:
        route = settings.nineclaw_route_gateway.format(instance_id=instance_id)
        return f"{settings.resolved_manager_traefik_url}{route}"


def _top_level_hermes_node(plan: dict, node_definition_id: str) -> dict:
    nodes = plan.get("nodes") if isinstance(plan, dict) else None
    node = nodes.get(node_definition_id) if isinstance(nodes, dict) else None
    if not isinstance(node, dict) or node.get("type") != "hermes_agent":
        raise ConversationValidationError(
            "仅已发布的顶层 Hermes 智能体节点支持独立对话"
        )
    return node


def _node_config(conversation: WorkflowNodeConversation) -> dict[str, Any]:
    config = conversation.node_snapshot.get("config")
    if not isinstance(config, dict):
        raise ConversationValidationError("对话节点快照无效")
    return config


def _build_turn_messages(
    config: dict[str, Any], turn: WorkflowNodeConversationTurn
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if turn.turn_number == 1 and isinstance(config.get("messages"), list):
        messages.extend(
            deepcopy(item) for item in config["messages"] if isinstance(item, dict)
        )
    messages.append(deepcopy(turn.user_message))
    return messages


def _build_conversation_instructions(config: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("instructions", "prompt"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return "\n\n".join(parts) or None


def _remote_status(payload: dict[str, Any]) -> str:
    containers = [payload]
    if isinstance(payload.get("data"), dict):
        containers.append(payload["data"])
    for container in containers:
        for key in ("status", "state"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower().replace("-", "_")
    return ""


def _extract_assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    output: Any = payload.get("output")
    if output is None:
        output = payload.get("output_text")
    if output is None and isinstance(payload.get("data"), dict):
        output = payload["data"].get("output") or payload["data"].get("output_text")
    if isinstance(output, dict):
        message = output.get("message")
        if isinstance(message, dict):
            return deepcopy(message)
        if "role" in output and "content" in output:
            return deepcopy(output)
        if "content" in output:
            return {"role": "assistant", "content": deepcopy(output["content"])}
        return {"role": "assistant", "content": deepcopy(output)}
    if isinstance(output, str):
        return {"role": "assistant", "content": output}
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return deepcopy(message)
    return {"role": "assistant", "content": ""}


def _extract_remote_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message[:2048]
    if isinstance(error, str) and error:
        return error[:2048]
    detail = payload.get("detail")
    if isinstance(detail, str) and detail:
        return detail[:2048]
    return "Hermes Run 执行失败"

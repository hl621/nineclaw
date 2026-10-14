"""PostgreSQL-backed worker for independent node-conversation Jobs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Awaitable
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.workflow import WorkflowNodeConversationJob, utcnow
from app.services.hermes_gateway_service import GatewayError, HermesGatewayService
from app.services.workflow.conversations import (
    ConversationAction,
    ConversationDispatch,
    ConversationMonitor,
    WorkflowConversationService,
)

logger = logging.getLogger(__name__)

# A definitive validation response proves the corresponding Hermes request was
# rejected before a Run/action could take effect.  Other failures are treated
# as unknown to prevent duplicated side effects.
_DEFINITE_REQUEST_REJECTIONS = {400, 401, 403, 404, 405, 422}


@dataclass(frozen=True)
class ClaimedConversationJob:
    id: UUID
    job_type: str
    fencing_token: int
    reclaimed: bool


class WorkflowConversationScheduler:
    """Claim durable conversation Jobs and call Hermes outside DB transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory
        self._worker_id = f"workflow-conversation-{uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is None and settings.workflow_scheduler_enabled:
            self._stopping.clear()
            self._task = asyncio.create_task(
                self._run(), name="workflow-conversation-scheduler"
            )

    async def close(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> bool:
        claimed = await self._claim_one()
        if claimed is None:
            return False
        try:
            await self._process(claimed)
        except Exception as exc:
            logger.exception(
                "workflow conversation job processing failed: job=%s type=%s",
                claimed.id,
                claimed.job_type,
            )
            await self._persist_internal_error(claimed, str(exc))
        return True

    async def _run(self) -> None:
        while not self._stopping.is_set():
            if await self.run_once():
                continue
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=settings.workflow_scheduler_poll_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def _claim_one(self) -> ClaimedConversationJob | None:
        now = utcnow()
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob)
                .where(
                    or_(
                        and_(
                            WorkflowNodeConversationJob.status == "queued",
                            WorkflowNodeConversationJob.available_at <= now,
                        ),
                        and_(
                            WorkflowNodeConversationJob.status == "running",
                            WorkflowNodeConversationJob.lease_expires_at.is_not(None),
                            WorkflowNodeConversationJob.lease_expires_at < now,
                        ),
                    )
                )
                .order_by(
                    WorkflowNodeConversationJob.available_at,
                    WorkflowNodeConversationJob.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            reclaimed = job.status == "running"
            job.status = "running"
            job.lease_owner = self._worker_id
            job.lease_expires_at = now + timedelta(
                seconds=settings.workflow_job_lease_seconds
            )
            job.fencing_token += 1
            job.updated_at = now
            await session.commit()
            return ClaimedConversationJob(
                id=job.id,
                job_type=job.job_type,
                fencing_token=job.fencing_token,
                reclaimed=reclaimed,
            )

    async def _process(self, claimed: ClaimedConversationJob) -> None:
        if claimed.job_type == "dispatch_turn":
            await self._process_dispatch(claimed)
        elif claimed.job_type == "monitor_turn":
            await self._process_monitor(claimed)
        elif claimed.job_type == "cancel_turn":
            await self._process_cancel(claimed)
        elif claimed.job_type == "approve_turn":
            await self._process_approval(claimed)
        else:
            raise RuntimeError(f"未知节点对话 Job 类型：{claimed.job_type}")

    async def _process_dispatch(self, claimed: ClaimedConversationJob) -> None:
        dispatch: ConversationDispatch | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob).where(
                    WorkflowNodeConversationJob.id == claimed.id
                )
            )
            if job is None:
                return
            dispatch = await WorkflowConversationService(session).prepare_dispatch(
                job=job,
                fencing_token=claimed.fencing_token,
                reclaimed=claimed.reclaimed,
            )
            await session.commit()
        if dispatch is None:
            return

        try:
            async with HermesGatewayService(
                dispatch.base_url,
                dispatch.api_key,
                timeout=settings.workflow_hermes_request_timeout,
            ) as gateway:
                payload = await self._await_with_lease(
                    claimed,
                    gateway.create_run(
                        dispatch.messages,
                        model=dispatch.model,
                        instructions=dispatch.instructions,
                        session_id=dispatch.session_id,
                        **dispatch.extra,
                    ),
                )
            external_run_id = _extract_run_id(payload)
            if external_run_id is None:
                raise _AmbiguousCreateError("Hermes 创建响应没有 run_id")
        except GatewayError as exc:
            if exc.status_code in _DEFINITE_REQUEST_REJECTIONS:
                async with self._sessions() as session:
                    await WorkflowConversationService(
                        session
                    ).persist_dispatch_rejected(
                        dispatch=dispatch,
                        error=exc.detail,
                    )
                    await session.commit()
            else:
                await self._persist_dispatch_uncertain(
                    dispatch, f"Hermes 创建失败：{exc.detail}"
                )
        except (httpx.RequestError, _AmbiguousCreateError, ValueError) as exc:
            await self._persist_dispatch_uncertain(
                dispatch, f"Hermes 创建结果未知：{exc}"
            )
        except Exception as exc:
            await self._persist_dispatch_uncertain(
                dispatch, f"Hermes 创建结果未知：{exc}"
            )
        else:
            async with self._sessions() as session:
                await WorkflowConversationService(session).persist_dispatched(
                    dispatch=dispatch,
                    external_run_id=external_run_id,
                )
                await session.commit()

    async def _process_monitor(self, claimed: ClaimedConversationJob) -> None:
        monitor: ConversationMonitor | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob).where(
                    WorkflowNodeConversationJob.id == claimed.id
                )
            )
            if job is None:
                return
            monitor = await WorkflowConversationService(session).prepare_monitor(
                job=job,
                fencing_token=claimed.fencing_token,
            )
            await session.commit()
        if monitor is None:
            return

        try:
            async with HermesGatewayService(
                monitor.base_url,
                monitor.api_key,
                timeout=settings.workflow_hermes_request_timeout,
            ) as gateway:
                payload = await self._await_with_lease(
                    claimed,
                    gateway.get_run(monitor.external_run_id),
                )
        except Exception as exc:
            logger.warning(
                "workflow conversation Hermes monitor failed: turn=%s error=%s",
                monitor.turn_id,
                exc,
            )
            async with self._sessions() as session:
                await WorkflowConversationService(session).release_monitor_after_error(
                    monitor=monitor
                )
                await session.commit()
            return
        if not isinstance(payload, dict):
            async with self._sessions() as session:
                await WorkflowConversationService(session).release_monitor_after_error(
                    monitor=monitor
                )
                await session.commit()
            return
        async with self._sessions() as session:
            await WorkflowConversationService(session).persist_monitor_result(
                monitor=monitor,
                payload=payload,
            )
            await session.commit()

    async def _process_cancel(self, claimed: ClaimedConversationJob) -> None:
        action: ConversationAction | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob).where(
                    WorkflowNodeConversationJob.id == claimed.id
                )
            )
            if job is None:
                return
            action = await WorkflowConversationService(session).prepare_cancel(
                job=job,
                fencing_token=claimed.fencing_token,
                reclaimed=claimed.reclaimed,
            )
            await session.commit()
        if action is None:
            return

        try:
            async with HermesGatewayService(
                action.base_url,
                action.api_key,
                timeout=settings.workflow_hermes_request_timeout,
            ) as gateway:
                await self._await_with_lease(
                    claimed,
                    gateway.stop_run(action.external_run_id),
                )
        except GatewayError as exc:
            if exc.status_code in _DEFINITE_REQUEST_REJECTIONS:
                async with self._sessions() as session:
                    await WorkflowConversationService(session).persist_cancel_rejected(
                        action=action,
                        error=exc.detail,
                    )
                    await session.commit()
            else:
                await self._persist_action_uncertain(
                    action,
                    action_name="cancel",
                    error=f"Hermes 取消结果未知：{exc.detail}",
                )
        except Exception as exc:
            await self._persist_action_uncertain(
                action,
                action_name="cancel",
                error=f"Hermes 取消结果未知：{exc}",
            )
        else:
            async with self._sessions() as session:
                await WorkflowConversationService(session).persist_cancel_accepted(
                    action=action
                )
                await session.commit()

    async def _process_approval(self, claimed: ClaimedConversationJob) -> None:
        action: ConversationAction | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob).where(
                    WorkflowNodeConversationJob.id == claimed.id
                )
            )
            if job is None:
                return
            action = await WorkflowConversationService(session).prepare_approval(
                job=job,
                fencing_token=claimed.fencing_token,
                reclaimed=claimed.reclaimed,
            )
            await session.commit()
        if action is None:
            return

        try:
            async with HermesGatewayService(
                action.base_url,
                action.api_key,
                timeout=settings.workflow_hermes_request_timeout,
            ) as gateway:
                await self._await_with_lease(
                    claimed,
                    gateway.approve_run(
                        action.external_run_id,
                        action.decision or "",
                        action.reason,
                    ),
                )
        except GatewayError as exc:
            if exc.status_code in _DEFINITE_REQUEST_REJECTIONS:
                async with self._sessions() as session:
                    await WorkflowConversationService(
                        session
                    ).persist_approval_rejected(
                        action=action,
                        error=exc.detail,
                    )
                    await session.commit()
            else:
                await self._persist_action_uncertain(
                    action,
                    action_name="approval",
                    error=f"Hermes 审批结果未知：{exc.detail}",
                )
        except Exception as exc:
            await self._persist_action_uncertain(
                action,
                action_name="approval",
                error=f"Hermes 审批结果未知：{exc}",
            )
        else:
            async with self._sessions() as session:
                await WorkflowConversationService(session).persist_approval_accepted(
                    action=action
                )
                await session.commit()

    async def _persist_dispatch_uncertain(
        self, dispatch: ConversationDispatch, error: str
    ) -> None:
        async with self._sessions() as session:
            await WorkflowConversationService(session).persist_dispatch_uncertain(
                dispatch=dispatch,
                error=error,
            )
            await session.commit()

    async def _persist_action_uncertain(
        self,
        action: ConversationAction,
        *,
        action_name: str,
        error: str,
    ) -> None:
        async with self._sessions() as session:
            await WorkflowConversationService(session).persist_action_uncertain(
                action=action,
                action_name=action_name,
                error=error,
            )
            await session.commit()

    async def _persist_internal_error(
        self, claimed: ClaimedConversationJob, error: str
    ) -> None:
        try:
            async with self._sessions() as session:
                await WorkflowConversationService(session).persist_internal_job_error(
                    job_id=claimed.id,
                    fencing_token=claimed.fencing_token,
                    error=error,
                )
                await session.commit()
        except Exception:
            logger.exception(
                "workflow conversation failed to persist internal job error: job=%s",
                claimed.id,
            )

    async def _await_with_lease(
        self, claimed: ClaimedConversationJob, operation: Awaitable[Any]
    ) -> Any:
        """Renew a Job lease while one external request is in flight."""

        task = asyncio.ensure_future(operation)
        interval = max(1.0, settings.workflow_job_lease_seconds / 3)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=interval)
                if done:
                    return task.result()
                if not await self._renew_lease(claimed):
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise _LeaseLostError("节点对话 Job 租约已失效")
        finally:
            if not task.done():
                task.cancel()

    async def _renew_lease(self, claimed: ClaimedConversationJob) -> bool:
        now = utcnow()
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowNodeConversationJob)
                .where(WorkflowNodeConversationJob.id == claimed.id)
                .with_for_update()
            )
            if (
                job is None
                or job.status != "running"
                or job.fencing_token != claimed.fencing_token
            ):
                return False
            job.lease_expires_at = now + timedelta(
                seconds=settings.workflow_job_lease_seconds
            )
            job.updated_at = now
            await session.commit()
            return True


class _AmbiguousCreateError(ValueError):
    pass


class _LeaseLostError(RuntimeError):
    pass


def _extract_run_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("run_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_run_id(data)
    return None

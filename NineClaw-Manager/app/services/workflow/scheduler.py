"""PostgreSQL-backed worker for workflow jobs."""

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
from app.models.workflow import WorkflowJob, utcnow
from app.services.hermes_gateway_service import GatewayError, HermesGatewayService
from app.services.workflow.engine import HermesDispatch, HermesMonitor, WorkflowEngine

logger = logging.getLogger(__name__)

# Only these responses are confirmed request-validation failures before a
# Hermes Run exists.  Other 4xx responses can pass through proxies after the
# upstream has accepted the request, so treating them as definite is unsafe.
_DEFINITE_CREATE_REJECTIONS = {400, 401, 403, 404, 405, 422}


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    job_type: str
    fencing_token: int


class WorkflowScheduler:
    """Claims one durable job at a time and never calls Hermes in a DB transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory
        self._worker_id = f"workflow-{uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is None and settings.workflow_scheduler_enabled:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="workflow-scheduler")

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
        except Exception:
            logger.exception(
                "workflow job processing failed: job=%s type=%s",
                claimed.id,
                claimed.job_type,
            )
            await self._release_after_internal_error(claimed)
        return True

    async def _run(self) -> None:
        while not self._stopping.is_set():
            processed = await self.run_once()
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(),
                        timeout=settings.workflow_scheduler_poll_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    async def _claim_one(self) -> ClaimedJob | None:
        now = utcnow()
        expired = now
        async with self._sessions() as session:
            stmt = (
                select(WorkflowJob)
                .where(
                    or_(
                        and_(
                            WorkflowJob.status == "queued",
                            WorkflowJob.available_at <= now,
                        ),
                        and_(
                            WorkflowJob.status == "running",
                            WorkflowJob.lease_expires_at.is_not(None),
                            WorkflowJob.lease_expires_at < expired,
                        ),
                    )
                )
                .order_by(WorkflowJob.available_at, WorkflowJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = await session.scalar(stmt)
            if job is None:
                return None
            job.status = "running"
            job.lease_owner = self._worker_id
            job.lease_expires_at = now + timedelta(
                seconds=settings.workflow_job_lease_seconds
            )
            job.fencing_token += 1
            job.updated_at = now
            await session.commit()
            return ClaimedJob(
                id=job.id, job_type=job.job_type, fencing_token=job.fencing_token
            )

    async def _process(self, claimed: ClaimedJob) -> None:
        if claimed.job_type == "dispatch_node":
            await self._process_dispatch(claimed)
        elif claimed.job_type == "monitor_hermes":
            await self._process_monitor(claimed)
        elif claimed.job_type == "cancel_hermes":
            await self._process_cancel(claimed)
        else:
            await self._finish_unknown_job(claimed)

    async def _process_dispatch(self, claimed: ClaimedJob) -> None:
        dispatch: HermesDispatch | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == claimed.id)
            )
            if job is None:
                return
            dispatch = await WorkflowEngine(session).prepare_dispatch(
                job=job, fencing_token=claimed.fencing_token, worker_id=self._worker_id
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
                response = await self._await_with_lease(
                    claimed,
                    gateway.create_run(
                        dispatch.messages,
                        model=dispatch.model,
                        instructions=dispatch.instructions,
                        session_id=dispatch.session_id,
                        **dispatch.extra,
                    ),
                )
            run_id = _extract_run_id(response)
            if run_id is None:
                raise _AmbiguousCreateError("Hermes 创建响应没有 run_id")
        except GatewayError as exc:
            if exc.status_code in _DEFINITE_CREATE_REJECTIONS:
                async with self._sessions() as session:
                    await WorkflowEngine(session).persist_hermes_rejected(
                        dispatch=dispatch, error=exc.detail
                    )
                    await session.commit()
            else:
                await self._persist_uncertain(
                    dispatch, f"Hermes 创建失败：{exc.detail}"
                )
        except (httpx.RequestError, _AmbiguousCreateError, ValueError) as exc:
            await self._persist_uncertain(dispatch, f"Hermes 创建结果未知：{exc}")
        except Exception as exc:
            await self._persist_uncertain(dispatch, f"Hermes 创建结果未知：{exc}")
        else:
            async with self._sessions() as session:
                await WorkflowEngine(session).persist_hermes_created(
                    dispatch=dispatch, external_run_id=run_id
                )
                await session.commit()

    async def _process_monitor(self, claimed: ClaimedJob) -> None:
        monitor: HermesMonitor | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == claimed.id)
            )
            if job is None:
                return
            monitor = await WorkflowEngine(session).prepare_monitor(
                job=job, fencing_token=claimed.fencing_token
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
                    claimed, gateway.get_run(monitor.external_run_id)
                )
        except Exception as exc:
            logger.warning(
                "workflow Hermes monitor failed: attempt=%s error=%s",
                monitor.attempt_id,
                exc,
            )
            async with self._sessions() as session:
                await WorkflowEngine(session).release_monitor_after_error(
                    monitor=monitor
                )
                await session.commit()
            return
        if not isinstance(payload, dict):
            logger.warning(
                "workflow Hermes monitor returned a non-object payload: attempt=%s",
                monitor.attempt_id,
            )
            async with self._sessions() as session:
                await WorkflowEngine(session).release_monitor_after_error(
                    monitor=monitor
                )
                await session.commit()
            return
        async with self._sessions() as session:
            await WorkflowEngine(session).persist_monitor_result(
                monitor=monitor, payload=payload
            )
            await session.commit()

    async def _process_cancel(self, claimed: ClaimedJob) -> None:
        cancel: HermesMonitor | None
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == claimed.id)
            )
            if job is None:
                return
            cancel = await WorkflowEngine(session).prepare_cancel(
                job=job, fencing_token=claimed.fencing_token
            )
            await session.commit()
        if cancel is None:
            return
        try:
            async with HermesGatewayService(
                cancel.base_url,
                cancel.api_key,
                timeout=settings.workflow_hermes_request_timeout,
            ) as gateway:
                await self._await_with_lease(
                    claimed, gateway.stop_run(cancel.external_run_id)
                )
        except Exception as exc:
            async with self._sessions() as session:
                await WorkflowEngine(session).persist_cancel_unconfirmed(
                    cancel=cancel, error=str(exc)
                )
                await session.commit()
        else:
            async with self._sessions() as session:
                await WorkflowEngine(session).persist_cancel_accepted(cancel=cancel)
                await session.commit()

    async def _persist_uncertain(self, dispatch: HermesDispatch, message: str) -> None:
        async with self._sessions() as session:
            await WorkflowEngine(session).persist_hermes_uncertain(
                dispatch=dispatch, error=message
            )
            await session.commit()

    async def _await_with_lease(
        self, claimed: ClaimedJob, operation: Awaitable[Any]
    ) -> Any:
        """Renew a Job lease while an external Hermes request is in flight."""
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
                    raise _LeaseLostError("工作流 Job 租约已失效")
        finally:
            if not task.done():
                task.cancel()

    async def _renew_lease(self, claimed: ClaimedJob) -> bool:
        now = utcnow()
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob)
                .where(WorkflowJob.id == claimed.id)
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

    async def _finish_unknown_job(self, claimed: ClaimedJob) -> None:
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == claimed.id)
            )
            if (
                job is not None
                and job.status == "running"
                and job.fencing_token == claimed.fencing_token
            ):
                job.status = "succeeded"
                job.updated_at = utcnow()
                await session.commit()

    async def _release_after_internal_error(self, claimed: ClaimedJob) -> None:
        async with self._sessions() as session:
            job = await session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == claimed.id)
            )
            if (
                job is not None
                and job.status == "running"
                and job.fencing_token == claimed.fencing_token
            ):
                job.status = "queued"
                job.available_at = utcnow() + timedelta(
                    seconds=settings.workflow_scheduler_poll_seconds
                )
                job.lease_owner = None
                job.lease_expires_at = None
                job.updated_at = utcnow()
                await session.commit()


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

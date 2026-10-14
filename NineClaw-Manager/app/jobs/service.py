"""Job service facade used by routes and task handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.jobs.models import JobEvent, JobEventLevel, JobRecord, JobStatus, utc_now
from app.jobs.store import InMemoryJobStore, job_store


class JobService:
    def __init__(self, store: InMemoryJobStore) -> None:
        self._store = store

    async def create_job(
        self,
        *,
        job_type: str,
        tenant_id: str = "default",
        resource_type: str | None = None,
        resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = await self._store.create(
            job_type=job_type,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )
        await self.emit(
            job.id,
            "queued",
            "任务已入队",
            progress=job.progress,
        )
        return job

    async def enqueue_job(
        self,
        *,
        job_type: str,
        tenant_id: str = "default",
        resource_type: str | None = None,
        resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JobRecord:
        from app.jobs.tasks import dispatch_job

        job = await self.create_job(
            job_type=job_type,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )
        await dispatch_job.kiq(job.id)
        return job

    async def get_job(self, job_id: str) -> JobRecord:
        return await self._store.get(job_id)

    async def list_jobs(self, *, limit: int = 100) -> list[JobRecord]:
        return await self._store.list(limit=limit)

    async def mark_running(self, job_id: str, message: str = "任务开始执行") -> JobRecord:
        job = await self._store.update(
            job_id,
            status=JobStatus.RUNNING,
            started_at=utc_now(),
        )
        await self.emit(job_id, "running", message, progress=job.progress)
        return job

    async def mark_waiting_external(
        self,
        job_id: str,
        message: str,
        *,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = await self._store.update(
            job_id,
            status=JobStatus.WAITING_EXTERNAL,
            progress=progress,
        )
        await self.emit(
            job_id,
            "waiting_external",
            message,
            progress=progress,
            data=data,
        )
        return job

    async def mark_succeeded(
        self,
        job_id: str,
        *,
        message: str = "任务已完成",
        result: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = await self._store.update(
            job_id,
            status=JobStatus.SUCCEEDED,
            progress=100,
            result=result,
            finished_at=utc_now(),
        )
        await self.emit(job_id, "succeeded", message, progress=100, data=result)
        return job

    async def mark_failed(
        self,
        job_id: str,
        *,
        message: str,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> JobRecord:
        detail = error or message
        job = await self._store.update(
            job_id,
            status=JobStatus.FAILED,
            error=detail,
            finished_at=utc_now(),
        )
        await self.emit(
            job_id,
            "failed",
            message,
            level=JobEventLevel.ERROR,
            data=data or {"error": detail},
        )
        return job

    async def request_cancel(self, job_id: str) -> JobRecord:
        job = await self._store.update(
            job_id,
            status=JobStatus.CANCEL_REQUESTED,
            cancel_requested_at=utc_now(),
        )
        await self.emit(
            job_id,
            "cancel_requested",
            "已请求取消任务",
            level=JobEventLevel.WARNING,
            progress=job.progress,
        )
        return job

    async def emit(
        self,
        job_id: str,
        event_type: str,
        message: str,
        *,
        level: JobEventLevel = JobEventLevel.INFO,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        if progress is not None:
            await self._store.update(job_id, progress=progress)
        return await self._store.append_event(
            job_id,
            event_type=event_type,
            message=message,
            level=level,
            progress=progress,
            data=data,
        )

    async def list_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[JobEvent]:
        return await self._store.list_events(job_id, after_sequence=after_sequence)

    def subscribe_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[JobEvent]:
        return self._store.subscribe(job_id, after_sequence=after_sequence)


job_service = JobService(job_store)

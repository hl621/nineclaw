"""In-memory job store with event subscriptions."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, AsyncIterator

from app.jobs.models import JobEvent, JobEventLevel, JobRecord, JobStatus, utc_now


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELED,
}


class JobNotFoundError(KeyError):
    pass


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._events: dict[str, list[JobEvent]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        job_type: str,
        tenant_id: str = "default",
        resource_type: str | None = None,
        resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JobRecord:
        now = utc_now()
        job = JobRecord(
            id=f"job_{uuid.uuid4().hex}",
            type=job_type,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> JobRecord:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            return job.model_copy(deep=True)

    async def list(self, *, limit: int = 100) -> list[JobRecord]:
        async with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )[:limit]
            return [job.model_copy(deep=True) for job in jobs]

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        cancel_requested_at: datetime | None = None,
    ) -> JobRecord:
        async with self._lock:
            current = self._jobs.get(job_id)
            if not current:
                raise JobNotFoundError(job_id)
            patch: dict[str, Any] = {"updated_at": utc_now()}
            if status is not None:
                patch["status"] = status
            if progress is not None:
                patch["progress"] = progress
            if result is not None:
                patch["result"] = result
            if error is not None:
                patch["error"] = error
            if started_at is not None:
                patch["started_at"] = started_at
            if finished_at is not None:
                patch["finished_at"] = finished_at
            if cancel_requested_at is not None:
                patch["cancel_requested_at"] = cancel_requested_at
            next_job = current.model_copy(update=patch)
            self._jobs[job_id] = next_job
            return next_job.model_copy(deep=True)

    async def append_event(
        self,
        job_id: str,
        *,
        event_type: str,
        message: str,
        level: JobEventLevel = JobEventLevel.INFO,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        async with self._lock:
            if job_id not in self._jobs:
                raise JobNotFoundError(job_id)
            seq = len(self._events[job_id]) + 1
            event = JobEvent(
                id=f"evt_{uuid.uuid4().hex}",
                job_id=job_id,
                sequence=seq,
                type=event_type,
                level=level,
                message=message,
                progress=progress,
                data=data or {},
            )
            self._events[job_id].append(event)
            subscribers = list(self._subscribers.get(job_id, set()))
        for queue in subscribers:
            queue.put_nowait(event)
        return event

    async def list_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[JobEvent]:
        async with self._lock:
            if job_id not in self._jobs:
                raise JobNotFoundError(job_id)
            events = [
                event.model_copy(deep=True)
                for event in self._events.get(job_id, [])
                if event.sequence > after_sequence
            ]
        return events

    async def subscribe(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        async with self._lock:
            if job_id not in self._jobs:
                raise JobNotFoundError(job_id)
            backfill = [
                event
                for event in self._events.get(job_id, [])
                if event.sequence > after_sequence
            ]
            self._subscribers[job_id].add(queue)
        try:
            for event in backfill:
                yield event.model_copy(deep=True)
            while True:
                event = await queue.get()
                yield event.model_copy(deep=True)
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(job_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(job_id, None)


job_store = InMemoryJobStore()

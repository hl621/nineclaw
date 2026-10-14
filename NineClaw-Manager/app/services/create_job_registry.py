"""Process-local registry for long-running nineclaw create jobs."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.core.datetime_utils import format_utc_z


def _utcnow_iso() -> str:
    return format_utc_z(datetime.now(timezone.utc))


@dataclass
class CreateJob:
    job_id: str
    tenant_id: str
    name: str
    instance_id: str | None = None
    status: str = "running"
    stage: str = "allocating"
    error: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)


class CreateJobRegistry:
    """Keeps recent create-job events available for reconnecting SSE clients."""

    def __init__(self, *, max_events_per_job: int = 200) -> None:
        self._jobs: dict[str, CreateJob] = {}
        self._max_events_per_job = max_events_per_job
        self._lock = asyncio.Lock()

    async def create(self, *, tenant_id: str, name: str) -> CreateJob:
        job = CreateJob(job_id=uuid.uuid4().hex, tenant_id=tenant_id, name=name)
        async with self._lock:
            self._jobs[job.job_id] = job
        return job

    async def publish(
        self,
        job_id: str,
        *,
        event: str,
        data: dict[str, Any],
        terminal: bool = False,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.updated_at = _utcnow_iso()
            job.instance_id = data.get("instance_id") or job.instance_id
            if event == "failed":
                job.status = "failed"
                job.stage = "failed"
                job.error = str(data.get("error") or "")
            elif event == "done":
                job.status = "succeeded"
                job.stage = "running"
            else:
                job.status = str(data.get("status") or "running")
                job.stage = str(data.get("stage") or job.stage)
            item = {"event": event, "data": data}
            job.events.append(item)
            if len(job.events) > self._max_events_per_job:
                job.events = job.events[-self._max_events_per_job :]
            subscribers = list(job.subscribers)
            if terminal:
                terminal_subscribers = subscribers
                job.subscribers.clear()
            else:
                terminal_subscribers = []

        for queue in subscribers:
            await queue.put(item)
        for queue in terminal_subscribers:
            await queue.put(None)

    async def get(self, job_id: str) -> CreateJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def subscribe(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            replay = list(job.events)
            terminal = job.status in {"succeeded", "failed"}
            if not terminal:
                job.subscribers.add(queue)

        for item in replay:
            yield item
        if terminal:
            return

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.subscribers.discard(queue)


create_job_registry = CreateJobRegistry()

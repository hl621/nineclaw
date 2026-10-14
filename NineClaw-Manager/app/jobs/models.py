"""In-process job and event models.

These models are intentionally backend-neutral.  The first implementation uses
memory, but the API shape is compatible with a future Redis Streams/Postgres
store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELING = "canceling"
    CANCELED = "canceled"


class JobEventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class JobRecord(BaseModel):
    id: str
    type: str
    tenant_id: str = "default"
    resource_type: str | None = None
    resource_id: str | None = None
    status: JobStatus = JobStatus.QUEUED
    progress: int | None = Field(default=None, ge=0, le=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested_at: datetime | None = None


class JobEvent(BaseModel):
    id: str
    job_id: str
    sequence: int
    type: str
    level: JobEventLevel = JobEventLevel.INFO
    message: str
    progress: int | None = Field(default=None, ge=0, le=100)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class JobCreateRequest(BaseModel):
    type: str
    tenant_id: str = "default"
    resource_type: str | None = None
    resource_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    job: JobRecord


class JobListResponse(BaseModel):
    items: list[JobRecord]
    total: int


class JobEventListResponse(BaseModel):
    items: list[JobEvent]
    total: int

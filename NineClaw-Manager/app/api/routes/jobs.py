"""Job inspection and event streaming routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.jobs.models import (
    JobCreateRequest,
    JobEvent,
    JobEventListResponse,
    JobListResponse,
    JobResponse,
)
from app.jobs.registry import has_job_handler, registered_job_types
from app.jobs.service import job_service
from app.jobs.store import JobNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _event_payload(event: JobEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


@router.get("", response_model=JobListResponse, summary="List recent jobs")
async def list_jobs(
    limit: int = Query(default=100, ge=1, le=500),
) -> JobListResponse:
    items = await job_service.list_jobs(limit=limit)
    return JobListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a registered background job",
)
async def create_job(body: JobCreateRequest) -> JobResponse:
    if not has_job_handler(body.type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"未知任务类型：{body.type}",
                "registered_types": registered_job_types(),
            },
        )
    job = await job_service.enqueue_job(
        job_type=body.type,
        tenant_id=body.tenant_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        payload=body.payload,
    )
    return JobResponse(job=job)


@router.get("/{job_id}", response_model=JobResponse, summary="Get a job")
async def get_job(job_id: str) -> JobResponse:
    try:
        job = await job_service.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from exc
    return JobResponse(job=job)


@router.post("/{job_id}/cancel", response_model=JobResponse, summary="Request job cancellation")
async def cancel_job(job_id: str) -> JobResponse:
    try:
        job = await job_service.request_cancel(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from exc
    return JobResponse(job=job)


@router.get(
    "/{job_id}/events",
    response_model=JobEventListResponse,
    summary="List job events",
)
async def list_job_events(
    job_id: str,
    after_sequence: int = Query(default=0, ge=0),
) -> JobEventListResponse:
    try:
        items = await job_service.list_events(job_id, after_sequence=after_sequence)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from exc
    return JobEventListResponse(items=items, total=len(items))


@router.get(
    "/{job_id}/events/stream",
    summary="Stream job events via SSE",
)
async def stream_job_events(
    request: Request,
    job_id: str,
    after_sequence: int = Query(default=0, ge=0),
) -> EventSourceResponse:
    try:
        await job_service.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from exc

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        next_heartbeat = 0
        try:
            async for event in job_service.subscribe_events(
                job_id,
                after_sequence=after_sequence,
            ):
                if await request.is_disconnected():
                    break
                yield {
                    "event": event.type,
                    "id": str(event.sequence),
                    "data": json.dumps(_event_payload(event), ensure_ascii=False),
                }
                next_heartbeat = 0
                if await request.is_disconnected():
                    break
                if next_heartbeat <= 0:
                    next_heartbeat = 1
        except asyncio.CancelledError:
            raise

    return EventSourceResponse(
        event_generator(),
        headers=SSE_HEADERS,
        ping=15,
    )

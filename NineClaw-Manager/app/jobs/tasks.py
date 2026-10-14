"""Taskiq dispatcher tasks."""

from __future__ import annotations

import logging

from app.jobs.broker import broker
from app.jobs.models import JobStatus
from app.jobs.registry import UnknownJobTypeError, get_job_handler
from app.jobs.service import job_service

logger = logging.getLogger(__name__)


@broker.task(task_name="jobs.dispatch")
async def dispatch_job(job_id: str) -> None:
    job = await job_service.get_job(job_id)
    if job.status == JobStatus.CANCEL_REQUESTED:
        await job_service.mark_failed(
            job_id,
            message="任务在执行前已被取消",
            error="cancel requested before dispatch",
        )
        return

    await job_service.mark_running(job_id)
    try:
        handler = get_job_handler(job.type)
        result = await handler(job)
    except UnknownJobTypeError as exc:
        await job_service.mark_failed(
            job_id,
            message=f"未知任务类型：{job.type}",
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("job failed: id=%s type=%s", job.id, job.type)
        await job_service.mark_failed(
            job_id,
            message="任务执行失败",
            error=str(exc),
        )
    else:
        latest = await job_service.get_job(job_id)
        if latest.status not in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELED,
        }:
            await job_service.mark_succeeded(job_id, result=result)

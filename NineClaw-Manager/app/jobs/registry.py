"""Registry for job handlers.

Routes create jobs by type.  Taskiq executes a small dispatcher task which then
looks up the concrete handler here.  This keeps Taskiq wiring out of business
modules and makes backend replacement easier.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.jobs.models import JobRecord

JobHandler = Callable[[JobRecord], Awaitable[dict | None]]

_handlers: dict[str, JobHandler] = {}


class UnknownJobTypeError(LookupError):
    pass


def register_job_handler(job_type: str, handler: JobHandler) -> None:
    if not job_type.strip():
        raise ValueError("job_type is required")
    _handlers[job_type] = handler


def get_job_handler(job_type: str) -> JobHandler:
    handler = _handlers.get(job_type)
    if handler is None:
        raise UnknownJobTypeError(job_type)
    return handler


def has_job_handler(job_type: str) -> bool:
    return job_type in _handlers


def registered_job_types() -> list[str]:
    return sorted(_handlers)

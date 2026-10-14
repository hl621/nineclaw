"""Bulkhead guard for blocking external dependency calls."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import anyio
from fastapi import HTTPException, status

from app.core.config import settings

P = ParamSpec("P")
R = TypeVar("R")


class ExternalCallBusyError(RuntimeError):
    def __init__(self, dependency: str) -> None:
        super().__init__(f"{dependency} 调用并发已满，请稍后重试")
        self.dependency = dependency


class ExternalCallGuard:
    def __init__(self) -> None:
        self._limiters: dict[str, anyio.CapacityLimiter] = {
            "ragflow": anyio.CapacityLimiter(settings.external_ragflow_max_concurrency),
        }

    async def run_sync(
        self,
        dependency: str,
        func: Callable[P, R],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        limiter = self._limiters.get(dependency)
        if limiter is None:
            limiter = anyio.CapacityLimiter(1)
            self._limiters[dependency] = limiter

        with anyio.move_on_after(settings.external_queue_wait_timeout_seconds) as scope:
            await limiter.acquire()
        if scope.cancel_called:
            raise ExternalCallBusyError(dependency)

        try:
            call = functools.partial(func, *args, **kwargs)
            return await anyio.to_thread.run_sync(call, abandon_on_cancel=True)
        finally:
            limiter.release()


def dependency_busy_http_error(exc: ExternalCallBusyError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
        headers={"Retry-After": "2"},
    )


external_call_guard = ExternalCallGuard()

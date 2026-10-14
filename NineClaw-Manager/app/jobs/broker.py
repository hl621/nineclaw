"""Taskiq broker configuration.

The first backend is intentionally in-memory.  Keep imports of this module
centralized so Redis can replace the broker without touching business routes.
"""

from __future__ import annotations

from taskiq import InMemoryBroker

from app.core.config import settings

if settings.job_backend != "memory":
    raise RuntimeError(
        f"Unsupported JOB_BACKEND={settings.job_backend!r}; only 'memory' is implemented"
    )

broker = InMemoryBroker()

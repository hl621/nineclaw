"""Development server entry point.

Run with: python run.py
"""

import asyncio
import sys

# aiohttp NamedPipeConnector (Docker Desktop npipe://) requires Proactor on Windows.
# Uvicorn/reload can otherwise leave a Selector loop and fail at startup.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # With reload=True, uvicorn's `asyncio_setup` force-switches the policy to
    # WindowsSelectorEventLoopPolicy (use_subprocess=True) in BOTH the supervisor
    # and the spawn-context worker, undoing the Proactor policy set above. That
    # makes aiodocker's NamedPipeConnector raise "Named Pipes only available in
    # proactor loop under windows". Re-bind that hook so every (re)spawned worker
    # stays on Proactor. This module is re-imported as __mp_main__ in workers, so
    # the patch is applied there too.
    import uvicorn.loops.asyncio as _uvicorn_asyncio_loops

    def _win_proactor_setup(use_subprocess: bool = False) -> None:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _uvicorn_asyncio_loops.asyncio_setup = _win_proactor_setup

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        loop="auto",
        log_level=settings.log_level.lower(),
    )

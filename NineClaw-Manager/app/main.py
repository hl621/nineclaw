"""FastAPI application entry point for Nineclaw Manager.

Initialises the FastAPI app, registers routes, configures CORS,
and manages the lifecycle of the Docker client connection.

"""

from __future__ import annotations

import asyncio
import logging
import sys

# Must run before uvicorn creates the loop: Docker Desktop npipe needs Proactor.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sse_starlette.sse import EventSourceResponse

from app.api.routes import (
    datasets,
    document_chunks,
    docker_images,
    instances,
    jobs,
    knowledge,
    knowledge_studio,
    providers,
    retrieval,
    skill_studio,
    skills,
    mcp_servers,
    web_sources,
    websearch_studio,
    workflow_conversations,
    workflow_workspace,
    workflows,
    settings as settings_routes,
)
from app.core.config import settings
from app.db.session import check_database_connection, format_database_connection_error
from app.jobs.broker import broker as taskiq_broker
from app.jobs import tasks as _job_tasks  # noqa: F401 - register Taskiq tasks
from app.services.docker_service import DockerService
from app.services.terminal_service import TerminalService
from app.services.workflow.artifact_gc import ArtifactGarbageCollector
from app.services.workflow.conversation_scheduler import WorkflowConversationScheduler
from app.services.workflow.scheduler import WorkflowScheduler
from app.db.session import async_session_maker

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Lifespan Context Manager ─────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    logger.info("Starting Nineclaw Manager application")
    await check_database_connection()
    logger.info("Database connection verified")
    await taskiq_broker.startup()
    logger.info("Taskiq in-memory broker initialised")

    docker_service = DockerService()
    await docker_service.connect()
    app.state.docker_service = docker_service
    terminal_service = TerminalService(docker_service)
    terminal_service.start()
    app.state.terminal_service = terminal_service
    workflow_scheduler = WorkflowScheduler(async_session_maker)
    await workflow_scheduler.start()
    app.state.workflow_scheduler = workflow_scheduler
    workflow_conversation_scheduler = WorkflowConversationScheduler(async_session_maker)
    await workflow_conversation_scheduler.start()
    app.state.workflow_conversation_scheduler = workflow_conversation_scheduler
    artifact_gc = ArtifactGarbageCollector(async_session_maker)
    await artifact_gc.start()
    app.state.workflow_artifact_gc = artifact_gc
    logger.info("Docker service initialised")

    try:
        yield
    finally:
        logger.info("Shutting down Nineclaw Manager application")
        await artifact_gc.close()
        await workflow_conversation_scheduler.close()
        await workflow_scheduler.close()
        await terminal_service.close()
        await docker_service.close()
        await taskiq_broker.shutdown()
        logger.info("Docker service closed")


# ─── FastAPI Application ──────────────────────────────────────────────────────


app = FastAPI(
    title="Nineclaw Manager",
    description="Multi-tenant container management backend platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
    expose_headers=settings.cors_expose_headers,
    max_age=settings.cors_max_age,
)


# ─── Exception Handlers ───────────────────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with detailed error messages."""
    logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Returns a generic message rather than echoing the exception text to
    avoid leaking implementation details. ``HTTPException`` is passed through.
    """
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, RequestValidationError):
        raise exc
    if _is_database_connection_error(exc):
        message = format_database_connection_error(exc)
        logger.error("Database connection error on %s:\n%s", request.url.path, message)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": message},
        )
    logger.exception("Unhandled exception on %s: %s", request.url.path, exc)
    # Surface exception type/message for local debugging of playground proxies.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": f"{exc.__class__.__name__}: {exc}",
        },
    )


def _is_database_connection_error(exc: BaseException) -> bool:
    """Return true for DB connection failures surfaced through SQLAlchemy/asyncpg."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ConnectionRefusedError):
            return True
        if isinstance(current, (OperationalError, InterfaceError)):
            return True
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        current = current.__cause__ or current.__context__
    return False


# ─── Routes ───────────────────────────────────────────────────────────────────


# All API routes live under a single /v1 prefix so the Traefik label can
# stay a one-liner (`PathPrefix(`/v1`)`). Operator endpoints (/health, /,
# /docs, /openapi.json) stay at the root because they're typically hit
# directly against the container, not via Traefik.
api_v1 = APIRouter(prefix="/v1")
api_v1.include_router(instances.router)
api_v1.include_router(docker_images.router)
api_v1.include_router(jobs.router)
api_v1.include_router(workflows.router)
api_v1.include_router(workflow_conversations.router)
api_v1.include_router(workflow_workspace.router)
api_v1.include_router(providers.models_router)
api_v1.include_router(providers.router)
api_v1.include_router(skills.router)
api_v1.include_router(skill_studio.router)
api_v1.include_router(mcp_servers.router)
# RAG deploy: register outside /knowledge/{kb_id} so POST never collides with
# path params (old builds match kb_id="deploy" and return 405).
_RAG_DEPLOY_SUMMARY = "流式将 RAG 配置部署到 NineClaw 实例（SSE，Hermes PUT /api/env）"
for _deploy_path in ("/knowledge-deploy", "/rag/deploy"):
    api_v1.add_api_route(
        _deploy_path,
        knowledge.deploy_knowledge,
        methods=["POST"],
        tags=["knowledge"],
        summary=_RAG_DEPLOY_SUMMARY,
        response_class=EventSourceResponse,
    )
api_v1.include_router(knowledge.router)
api_v1.include_router(knowledge_studio.router)
api_v1.include_router(datasets.router)
api_v1.include_router(document_chunks.router)
api_v1.include_router(retrieval.router)
api_v1.include_router(web_sources.router)
api_v1.include_router(websearch_studio.router)
api_v1.include_router(settings_routes.router)
app.include_router(api_v1)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint with API information."""
    return {
        "service": "Nineclaw Manager",
        "version": "0.1.0",
        "docs": "/docs",
        "api_prefix": "/v1",
    }

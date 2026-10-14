"""Nineclaw Instance API Routes.

RESTful API for nineclaw container lifecycle management.

Routes:
- POST   /container/nineclaw              - Create instance
- GET    /container/nineclaw              - List instances
- GET    /container/nineclaw/{id}         - Get instance details
- PATCH  /container/nineclaw/{id}         - Update instance metadata (name, etc.)
- DELETE /container/nineclaw              - Delete instances (batch)
- DELETE /container/nineclaw/{id}         - Delete single instance
- POST   /container/nineclaw/{id}/start   - Start instance
- POST   /container/nineclaw/{id}/stop    - Stop instance
- POST   /container/nineclaw/{id}/restart - Restart instance
- GET    /container/nineclaw/{id}/logs    - Stream container logs (SSE)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import httpx
from aiodocker.exceptions import DockerError
from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.routes.skills import _existing_skill_dirs
from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.instance import ServiceInstance
from app.schemas.instance import InstanceCreate, InstanceDetail, InstanceResponse, InstanceUpdate
from app.services.docker_service import DockerService
from app.services.create_job_registry import create_job_registry
from app.services.docker_client import create_configured_docker_client
# 临时关闭首页「次执行」统计接口
# from app.services.hermes_webui_service import (
#     fetch_instance_conversation_rounds,
#     fetch_instances_conversation_rounds,
# )
from app.services.instance_service import (
    InstanceConflictError,
    InstanceNotFoundError,
    InstanceService,
    PortAllocationError,
)
from app.services.nineclaw_bootstrap import BootstrapError
from app.services.terminal_service import TerminalLimitError, TerminalService

logger = logging.getLogger(__name__)

TENANT_HEADER = "X-Tenant-ID"

router = APIRouter(
    prefix="/container/nineclaw",
    tags=["nineclaw"],
)


# ─── Request/Response Models ───────────────────────────────────────────────────


class ConversationRoundsBatchRequest(BaseModel):
    """Request body for batch conversation-round stats."""

    ids: list[str] = Field(default_factory=list, description="Instance IDs to query")


class ConversationRoundsResponse(BaseModel):
    """Conversation-round stats for one instance."""

    instance_id: str
    rounds: int = Field(ge=0)


class ConversationRoundsBatchResponse(BaseModel):
    """Conversation-round stats keyed by instance id."""

    items: dict[str, int] = Field(default_factory=dict)


class DeleteInstancesRequest(BaseModel):
    """Request body for batch delete instances."""

    ids: list[str] = Field(default_factory=list, description="Instance IDs to delete")
    delete_all: bool = Field(
        default=False, description="Delete all instances if ids is empty"
    )


class ApiResponse(BaseModel):
    """Standard API response wrapper."""

    code: int = Field(default=0, description="Response code, 0 means success")
    message: str = Field(default="success", description="Response message")
    data: Any = Field(default=None, description="Response data")


class TerminalCreateRequest(BaseModel):
    """Request body for creating an interactive terminal."""

    cols: int = Field(default=120, ge=1, le=400)
    rows: int = Field(default=32, ge=1, le=200)


class DirectoryEntry(BaseModel):
    """Directory entry inside a nineclaw container."""

    name: str
    path: str
    is_symlink: bool = False


class DirectoryListResponse(BaseModel):
    """Directory browser response for selecting a workspace path."""

    path: str
    parent: str | None = None
    entries: list[DirectoryEntry] = Field(default_factory=list)


def _is_remote_docker_auth_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "cannot connect to docker via ssh" in lowered
        and ("permission denied" in lowered or "authentication" in lowered)
    )


def _docker_terminal_error_detail(exc: DockerError) -> str:
    import re

    from app.services.docker_service import missing_image_message

    message = str(exc.message)
    if _is_remote_docker_auth_error(message):
        return (
            "远程 Docker SSH 鉴权失败。请在系统设置里重新保存远程 Docker 的 "
            "SSH 用户名/密码，或确认 Manager 进程使用的是最新配置。"
        )
    lowered = message.lower()
    if "no such container" in lowered or (exc.status == 404 and "container" in lowered):
        return (
            "当前 Docker 引擎上找不到该实例容器。"
            "若容器跑在远程机器上，请在系统设置配置远程 SSH Docker，"
            "并确认 Manager 已切换到该远程引擎后再打开终端。"
        )
    configured = settings.nineclaw_image_repository
    match = re.search(r"no such image:\s*(\S+)", message, flags=re.IGNORECASE)
    requested = match.group(1).rstrip(".,;") if match else ""
    if (
        "no such image" in lowered
        or ("not found" in lowered and "image" in lowered)
        or (exc.status == 404 and "image" in lowered)
    ):
        return missing_image_message(requested or configured)
    return f"Docker operation failed: {message}"


DIRECTORY_BROWSER_SCRIPT = r"""
import json
import os
import sys

path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "/"
path = os.path.abspath(os.path.expanduser(path))
if not os.path.exists(path):
    print(json.dumps({"error": f"Path does not exist: {path}"}, ensure_ascii=False))
    sys.exit(2)
if not os.path.isdir(path):
    print(json.dumps({"error": f"Path is not a directory: {path}"}, ensure_ascii=False))
    sys.exit(3)

entries = []
try:
    with os.scandir(path) as it:
        for item in it:
            try:
                if not item.is_dir(follow_symlinks=False):
                    continue
                entries.append({
                    "name": item.name,
                    "path": item.path,
                    "is_symlink": item.is_symlink(),
                })
            except OSError:
                continue
except PermissionError:
    print(json.dumps({"error": f"Permission denied: {path}"}, ensure_ascii=False))
    sys.exit(4)

entries.sort(key=lambda item: (item["name"].startswith("."), item["name"].lower()))
print(json.dumps({
    "path": path,
    "parent": None if path == "/" else os.path.dirname(path),
    "entries": entries[:500],
}, ensure_ascii=False))
"""


# ─── Dependency Helpers ───────────────────────────────────────────────────────


def get_docker_service(request: Request) -> DockerService:
    """Return the application-level DockerService stored in app.state."""
    return request.app.state.docker_service


def get_terminal_service(request: Request) -> TerminalService:
    """Return the process-local terminal registry."""
    return request.app.state.terminal_service


async def get_instance_service(
    session: AsyncSession = Depends(get_session),
    docker_service: DockerService = Depends(get_docker_service),
) -> InstanceService:
    """Build an InstanceService for the current request."""
    return InstanceService(session=session, docker_service=docker_service)


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    """Extract tenant ID from the X-Tenant-ID request header."""
    return x_tenant_id or settings.default_tenant_id


@router.get(
    "/{instance_id}/model/options",
    response_model=ApiResponse,
    summary="List selectable provider models and MoA presets",
)
async def get_manager_model_options(
    instance_id: str,
    profile: str | None = None,
    refresh: bool = False,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    """Build selectable custom-provider and MoA models from Dashboard config."""
    del profile, refresh
    instance = await session.scalar(
        select(ServiceInstance).where(
            ServiceInstance.id == instance_id,
            ServiceInstance.tenant_id == tenant_id,
        )
    )
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )

    from app.services.hermes_dashboard_service import HermesError, HermesService
    from app.services.model_options_service import build_model_options_from_config
    from app.services.nineclaw_bootstrap import build_dashboard_base_url
    try:
        async with HermesService(
            base_url=build_dashboard_base_url(instance_id),
            api_key=settings.nineclaw_token,
        ) as dashboard:
            config = await dashboard.get_config()
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Dashboard model options request timed out",
        ) from exc
    except HermesError as exc:
        logger.warning(
            "model options request failed for %s: Dashboard status %s",
            instance_id,
            exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dashboard model options are unavailable",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dashboard model options are unavailable",
        ) from exc

    try:
        data = build_model_options_from_config(config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dashboard model configuration is invalid",
        ) from exc

    return ApiResponse(data=data)


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new nineclaw instance",
)
async def create_instance(
    body: InstanceCreate,
    svc: InstanceService = Depends(get_instance_service),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Create a new nineclaw container instance."""
    try:
        instance = await svc.create_instance(
            name=body.name,
            image=body.image,
            tenant_id=tenant_id,
            environment=body.environment or {},
            volumes=body.volumes or [],
            memory_limit=body.memory,
            cpu_limit=body.cpus,
            config_overrides=body.config or {},
            env_overrides=body.env or {},
            initial_setup=body.initial_setup,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PortAllocationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InstanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BootstrapError as exc:
        # Container is up but its dashboard wouldn't accept the predefined
        # model/env config. Treat as 502 — the container exists (DELETE
        # will clean it up) but it isn't ready to serve traffic.
        logger.error("Bootstrap failed during create: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Instance bootstrap failed: {exc}",
        ) from exc
    except DockerError as exc:
        logger.exception("Docker error while creating instance")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_docker_terminal_error_detail(exc),
        ) from exc

    return ApiResponse(
        data=InstanceDetail.from_orm_instance(instance).model_dump(),
    )


@router.post(
    "/create-stream",
    summary="Create a new nineclaw instance with SSE progress",
)
async def create_instance_stream(
    body: InstanceCreate,
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> EventSourceResponse:
    """Create a nineclaw container and stream lifecycle progress."""
    job = await create_job_registry.create(tenant_id=tenant_id, name=body.name)
    logger.info(
        "create-stream request accepted: job=%s tenant=%s name=%s has_initial_setup=%s",
        job.job_id,
        tenant_id,
        body.name,
        body.initial_setup is not None,
    )

    async def event_stream():
        async def progress(stage: str, payload: dict[str, Any]) -> None:
            logger.info(
                "create-stream progress: job=%s instance=%s stage=%s payload_keys=%s",
                job.job_id,
                payload.get("instance_id"),
                stage,
                sorted(payload.keys()),
            )
            await _publish_create_stream_event(
                job.job_id,
                event="status",
                data=payload,
            )

        async def worker() -> None:
            try:
                logger.info(
                    "create-stream worker started: job=%s tenant=%s name=%s",
                    job.job_id,
                    tenant_id,
                    body.name,
                )
                async with async_session_maker() as session:
                    svc = InstanceService(
                        session=session,
                        docker_service=request.app.state.docker_service,
                    )
                    instance = await svc.create_instance(
                        name=body.name,
                        image=body.image,
                        tenant_id=tenant_id,
                        environment=body.environment or {},
                        volumes=body.volumes or [],
                        memory_limit=body.memory,
                        cpu_limit=body.cpus,
                        config_overrides=body.config or {},
                        env_overrides=body.env or {},
                        initial_setup=body.initial_setup,
                        progress=progress,
                        create_job_id=job.job_id,
                    )
                logger.info(
                    "create-stream worker completed: job=%s instance=%s",
                    job.job_id,
                    instance.id,
                )
                await _publish_create_stream_event(
                    job.job_id,
                    event="done",
                    data={
                        "instance_id": instance.id,
                        "instance": InstanceDetail.from_orm_instance(instance).model_dump(),
                    },
                    terminal=True,
                )
            except PortAllocationError as exc:
                logger.warning("create-stream port allocation failed: %s", exc)
                await _publish_create_stream_failed(job.job_id, str(exc))
            except ValueError as exc:
                logger.warning("create-stream validation failed: %s", exc)
                await _publish_create_stream_failed(job.job_id, str(exc))
            except BootstrapError as exc:
                logger.error("Bootstrap failed during streaming create: %s", exc)
                await _publish_create_stream_failed(job.job_id, f"Instance bootstrap failed: {exc}")
            except DockerError as exc:
                logger.exception("Docker error while streaming instance create")
                await _publish_create_stream_failed(
                    job.job_id, _docker_terminal_error_detail(exc)
                )
            except Exception as exc:
                logger.exception("Unexpected error while streaming instance create")
                await _publish_create_stream_failed(job.job_id, str(exc))
            finally:
                logger.info(
                    "create-stream worker finished terminal publish: job=%s name=%s",
                    job.job_id,
                    body.name,
                )

        task = asyncio.create_task(worker())
        await create_job_registry.publish(
            job.job_id,
            event="status",
            data={
                "job_id": job.job_id,
                "stage": "allocating",
                "status": "running",
                "name": body.name,
            },
        )
        try:
            async for item in create_job_registry.subscribe(job.job_id):
                logger.debug(
                    "create-stream yield event: job=%s event=%s",
                    job.job_id,
                    item.get("event"),
                )
                yield _format_create_sse_item(item)
        finally:
            if not task.done():
                logger.warning(
                    "create-stream client disconnected; worker will continue in background for job=%s name=%s",
                    job.job_id,
                    body.name,
                )

    return EventSourceResponse(event_stream())


@router.get(
    "/create-stream/{job_id}",
    summary="Resume a nineclaw create SSE stream",
)
async def resume_create_instance_stream(
    job_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> EventSourceResponse:
    """Replay and continue a process-local create job stream."""
    job = await create_job_registry.get(job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Create job not found")

    logger.info(
        "create-stream resume accepted: job=%s tenant=%s status=%s stage=%s",
        job_id,
        tenant_id,
        job.status,
        job.stage,
    )

    async def event_stream():
        async for item in create_job_registry.subscribe(job_id):
            yield _format_create_sse_item(item)

    return EventSourceResponse(event_stream())


async def _publish_create_stream_event(
    job_id: str,
    *,
    event: str,
    data: dict[str, Any],
    terminal: bool = False,
) -> None:
    await create_job_registry.publish(
        job_id,
        event=event,
        data={"job_id": job_id, **data},
        terminal=terminal,
    )


async def _publish_create_stream_failed(job_id: str, message: str) -> None:
    await _publish_create_stream_event(
        job_id,
        event="failed",
        data={
            "stage": "failed",
            "status": "failed",
            "error": message,
        },
        terminal=True,
    )


def _format_create_sse_item(item: dict[str, Any]) -> dict[str, str]:
    return {
        "event": str(item.get("event") or "status"),
        "data": json.dumps(item.get("data") or {}, ensure_ascii=False, default=str),
    }


@router.get(
    "",
    response_model=ApiResponse,
    summary="List nineclaw instances",
)
async def list_instances(
    tenant_id: str = Depends(get_tenant_id),
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    """List all instances for the current tenant."""
    instances = await svc.list_instances(tenant_id=tenant_id)
    items = [InstanceResponse.from_orm_instance(i).model_dump() for i in instances]
    return ApiResponse(data={"items": items, "total": len(items)})


# @router.post(
#     "/stats/conversation-rounds",
#     response_model=ApiResponse,
#     summary="Batch conversation-round totals for instances",
# )
# async def batch_conversation_rounds(
#     body: ConversationRoundsBatchRequest,
# ) -> ApiResponse:
#     """Aggregate Hermes WebUI conversation rounds per instance (server-side)."""
#     items = await fetch_instances_conversation_rounds(body.ids)
#     return ApiResponse(data=ConversationRoundsBatchResponse(items=items).model_dump())


@router.patch(
    "/{instance_id}",
    response_model=ApiResponse,
    summary="Update instance metadata",
)
async def update_instance(
    instance_id: str,
    body: InstanceUpdate,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    """Update name, resource limits, or environment stored for an instance."""
    if (
        body.name is None
        and body.memory is None
        and body.cpus is None
        and body.environment is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided",
        )
    try:
        instance = await svc.update_instance(
            instance_id,
            name=body.name,
            memory_limit=body.memory,
            cpu_limit=body.cpus,
            environment=body.environment,
        )
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InstanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ApiResponse(
        data=InstanceDetail.from_orm_instance(instance).model_dump(),
    )


@router.get(
    "/{instance_id}",
    response_model=ApiResponse,
    summary="Get instance details",
)
async def get_instance(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    """Get full details for a specific instance."""
    try:
        instance = await svc.get_instance(instance_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ApiResponse(
        data=InstanceDetail.from_orm_instance(instance).model_dump(),
    )


# @router.get(
#     "/{instance_id}/stats/conversation-rounds",
#     response_model=ApiResponse,
#     summary="Conversation-round total for one instance",
# )
# async def get_conversation_rounds(
#     instance_id: str,
#     svc: InstanceService = Depends(get_instance_service),
# ) -> ApiResponse:
#     """Aggregate Hermes WebUI conversation rounds for a single instance."""
#     try:
#         await svc.get_instance(instance_id, refresh=False)
#     except InstanceNotFoundError as exc:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
#
#     rounds = await fetch_instance_conversation_rounds(instance_id)
#     return ApiResponse(
#         data=ConversationRoundsResponse(instance_id=instance_id, rounds=rounds).model_dump(),
#     )


@router.get(
    "/{instance_id}/directories",
    response_model=ApiResponse,
    summary="Browse directories inside a nineclaw container",
)
async def browse_directories(
    instance_id: str,
    path: str = "/opt/data/workspace",
    svc: InstanceService = Depends(get_instance_service),
    docker_service: DockerService = Depends(get_docker_service),
) -> ApiResponse:
    """List directories inside the target container for workspace selection."""
    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not instance.container_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instance has no container")
    if instance.actual_state != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not running: {instance.actual_state}",
        )

    try:
        exit_code, output = await docker_service.exec_container_output(
            instance.container_id,
            ["python3", "-c", DIRECTORY_BROWSER_SCRIPT, path],
            timeout=5.0,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Directory browse timed out",
        ) from exc
    except DockerError as exc:
        logger.exception("Docker error while browsing directories for %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc

    try:
        payload = json.loads(output.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Directory browse returned invalid output: {output[:200]}",
        ) from exc
    if exit_code not in (0, None) or payload.get("error"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=payload.get("error") or f"Directory browse failed with exit code {exit_code}",
        )

    return ApiResponse(data=DirectoryListResponse(**payload).model_dump())


@router.get(
    "/{instance_id}/terminals",
    response_model=ApiResponse,
    summary="List interactive terminals for an instance",
)
async def list_terminals(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """List process-local terminal sessions bound to a nineclaw instance."""
    try:
        await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(data={"items": await terminal_service.list_terminals(instance_id)})


@router.post(
    "/{instance_id}/terminals",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an interactive terminal for an instance",
)
async def create_terminal(
    instance_id: str,
    body: TerminalCreateRequest,
    svc: InstanceService = Depends(get_instance_service),
    docker_service: DockerService = Depends(get_docker_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """Create a Docker exec PTY inside the target nineclaw container."""
    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not instance.container_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instance has no container")
    if instance.actual_state != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not running: {instance.actual_state}",
        )
    async def _create() -> dict:
        return await terminal_service.create_terminal(
            instance_id=instance_id,
            container_id=instance.container_id or "",
            cols=body.cols,
            rows=body.rows,
        )

    try:
        terminal = await _create()
    except TerminalLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DockerError as exc:
        message = str(exc.message)
        if _is_remote_docker_auth_error(message):
            logger.warning(
                "Remote Docker SSH auth failed while creating terminal for %s; "
                "reconnecting Docker client and retrying once",
                instance_id,
            )
            try:
                # Remote Docker credentials are stored in DB and can be updated
                # while the FastAPI process is still alive. The app-level
                # Docker client may still hold the old SSH URL/options, so an
                # auth failure during terminal creation gets one reconnect
                # before surfacing an error to the user.
                await docker_service.close()
                await docker_service.connect()
                terminal = await _create()
            except TerminalLimitError as retry_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(retry_exc),
                ) from retry_exc
            except DockerError as retry_exc:
                logger.exception(
                    "Docker error while creating terminal for %s after reconnect",
                    instance_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=_docker_terminal_error_detail(retry_exc),
                ) from retry_exc
        else:
            logger.exception("Docker error while creating terminal for %s", instance_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_docker_terminal_error_detail(exc),
            ) from exc
    return ApiResponse(data=terminal)


@router.delete(
    "/{instance_id}/terminals/{terminal_id}",
    response_model=ApiResponse,
    summary="Close an interactive terminal",
)
async def close_terminal(
    instance_id: str,
    terminal_id: str,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """Close a terminal session and terminate its Docker exec shell."""
    try:
        await svc.get_instance(instance_id, refresh=False)
        await terminal_service.close_terminal(instance_id, terminal_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KeyError:
        logger.info("Terminal %s for instance %s was already closed", terminal_id, instance_id)
    return ApiResponse(data={"closed": terminal_id})


@router.websocket("/{instance_id}/terminals/{terminal_id}/ws")
async def terminal_websocket(
    websocket: WebSocket,
    instance_id: str,
    terminal_id: str,
) -> None:
    """Attach a browser WebSocket to an interactive Docker exec PTY."""
    terminal_service: TerminalService = websocket.app.state.terminal_service
    await websocket.accept()
    try:
        client = await terminal_service.attach(instance_id, terminal_id)
    except KeyError:
        await websocket.send_json({"type": "error", "message": "Terminal not found"})
        await websocket.close(code=1008)
        return

    async def sender() -> None:
        while True:
            payload = await client.queue.get()
            await websocket.send_json(payload)
            if payload.get("type") == "closed":
                break

    sender_task = asyncio.create_task(sender())
    try:
        while True:
            payload = await websocket.receive_json()
            msg_type = payload.get("type")
            if msg_type == "input":
                await terminal_service.write(instance_id, terminal_id, str(payload.get("data") or ""))
            elif msg_type == "resize":
                await terminal_service.resize(
                    instance_id,
                    terminal_id,
                    int(payload.get("cols") or 120),
                    int(payload.get("rows") or 32),
                )
            elif msg_type == "close":
                await terminal_service.close_terminal(instance_id, terminal_id)
                break
    except WebSocketDisconnect:
        pass
    except KeyError:
        await websocket.send_json({"type": "error", "message": "Terminal not found"})
    except Exception as exc:
        logger.exception("Terminal websocket failed for %s/%s", instance_id, terminal_id)
        await websocket.send_json({"type": "error", "message": str(exc)})
    finally:
        sender_task.cancel()
        with suppress(asyncio.CancelledError):
            await sender_task
        await terminal_service.detach(instance_id, terminal_id, client)


@router.delete(
    "",
    response_model=ApiResponse,
    summary="Delete instances (batch)",
)
async def delete_instances(
    body: DeleteInstancesRequest,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Delete instances by IDs or delete all for the current tenant."""
    target_ids = list(body.ids)
    if body.delete_all and not target_ids:
        instances = await svc.list_instances(tenant_id=tenant_id)
        target_ids = [i.id for i in instances]

    deleted_ids: list[str] = []
    errors: list[str] = []

    for instance_id in target_ids:
        try:
            await terminal_service.close_instance(instance_id, reason="instance deleted")
            await svc.delete_instance(instance_id)
            deleted_ids.append(instance_id)
        except InstanceNotFoundError:
            errors.append(f"Instance '{instance_id}' not found")
        except DockerError as exc:
            errors.append(f"Failed to delete '{instance_id}': {exc.message}")

    if errors and not deleted_ids:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="; ".join(errors),
        )

    data = {"deleted": deleted_ids}
    if errors:
        data["errors"] = errors

    return ApiResponse(
        code=0 if not errors else 1,
        message="partial success" if errors else "success",
        data=data,
    )


@router.delete(
    "/{instance_id}",
    response_model=ApiResponse,
    summary="Delete a single instance",
)
async def delete_instance(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """Delete a single nineclaw instance."""
    try:
        await terminal_service.close_instance(instance_id, reason="instance deleted")
        await svc.delete_instance(instance_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DockerError as exc:
        logger.exception("Docker error while deleting instance %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc

    return ApiResponse(data={"deleted": instance_id})


@router.post(
    "/{instance_id}/start",
    response_model=ApiResponse,
    summary="Start a stopped instance",
)
async def start_instance(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    """Start a stopped nineclaw instance."""
    try:
        instance = await svc.start_instance(instance_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InstanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DockerError as exc:
        logger.exception("Docker error while starting instance %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc

    return ApiResponse(data=InstanceResponse.from_orm_instance(instance).model_dump())


@router.post(
    "/{instance_id}/stop",
    response_model=ApiResponse,
    summary="Stop a running instance",
)
async def stop_instance(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """Stop a running nineclaw instance."""
    try:
        await terminal_service.close_instance(instance_id, reason="instance stopped")
        instance = await svc.stop_instance(instance_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InstanceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DockerError as exc:
        logger.exception("Docker error while stopping instance %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc

    return ApiResponse(data=InstanceResponse.from_orm_instance(instance).model_dump())


@router.post(
    "/{instance_id}/restart",
    response_model=ApiResponse,
    summary="Restart an instance",
)
async def restart_instance(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    terminal_service: TerminalService = Depends(get_terminal_service),
) -> ApiResponse:
    """Restart a nineclaw instance."""
    try:
        await terminal_service.close_instance(instance_id, reason="instance restarted")
        instance = await svc.restart_instance(instance_id)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DockerError as exc:
        logger.exception("Docker error while restarting instance %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc

    return ApiResponse(data=InstanceResponse.from_orm_instance(instance).model_dump())


@router.get(
    "/{instance_id}/logs",
    summary="Stream container logs (SSE)",
)
async def stream_logs(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    docker_service: DockerService = Depends(get_docker_service),
    tail: int = 100,
):
    """Stream container logs via Server-Sent Events.

    Args:
        instance_id: Instance ID.
        tail: Number of lines from the end to start with (default 100).
    """

    async def event_generator():
        try:
            instance = await svc.get_instance(instance_id)
            if not instance.container_id:
                yield {"event": "error", "data": "No container associated with this instance"}
                return

            async for line in docker_service.stream_logs(
                instance.container_id,
                follow=True,
                tail=tail,
            ):
                yield {"data": line}

        except InstanceNotFoundError:
            yield {"event": "error", "data": f"Instance '{instance_id}' not found"}
        except Exception as exc:
            logger.exception("Failed to stream logs for %s: %s", instance_id, exc)
            yield {"event": "error", "data": str(exc)}

    return EventSourceResponse(event_generator())


@router.get(
    "/{instance_id}/bundled-skills",
    summary="List bundled (image built-in) skill slugs inside the instance container",
)
async def get_instance_bundled_skills(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
    docker_service: DockerService = Depends(get_docker_service),
):
    """Read ``/opt/data/skills/.bundled_manifest`` from the instance container.

    Returns the list of image-bundled skill slugs so the frontend can tell
    built-in skills (shared by every instance of the image) apart from the
    instance's own skills (selected at creation / deployed later).
    """
    try:
        instance = await svc.get_instance(instance_id)
    except InstanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance '{instance_id}' not found",
        )
    if not instance.container_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No container associated with this instance",
        )
    try:
        exit_code, output = await docker_service.exec_container_output(
            instance.container_id,
            ["cat", "/opt/data/skills/.bundled_manifest"],
            timeout=8.0,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to client
        logger.warning(
            "Failed to read bundled manifest for %s: %s", instance_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"读取内置技能清单失败：{exc}",
        ) from exc

    slugs: list[str] = []
    if exit_code in (0, None) and output.strip():
        for line in output.splitlines():
            slug = line.split(":", 1)[0].strip()
            if slug and not slug.startswith("#"):
                slugs.append(slug)
    return {"code": 0, "message": "success", "data": {"bundled": slugs}}


@router.get(
    "/{instance_id}/skills/{skill_name}/download",
    summary="Download a skill folder inside the instance container as a zip archive",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive of the whole skill folder (SKILL.md + scripts/assets/...).",
        }
    },
)
async def download_instance_skill(
    instance_id: str,
    skill_name: str,
    tenant_id: str = Depends(get_tenant_id),
    svc: InstanceService = Depends(get_instance_service),
) -> Response:
    """Package an instance-local skill directory as a zip for download.

    Instance skills live under Hermes' native scan root ``/opt/data/skills`` —
    either ``/opt/data/skills/{slug}/`` or ``/opt/data/skills/{category}/{slug}/``.
    The whole folder is streamed from the container via the Docker archive
    API and repackaged as a zip so the WebUI can offer a "download full
    skill package" action (instead of only the SKILL.md body).
    """
    try:
        instance = await svc.get_instance(instance_id)
    except InstanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance '{instance_id}' not found",
        )
    if not instance.container_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No container associated with this instance",
        )

    docker = await create_configured_docker_client(tenant_id=tenant_id)
    try:
        container = await docker.containers.get(instance.container_id)
        # Same discovery logic as the deploy flow: dir basename -> path for
        # every SKILL.md found under /opt/data/skills (depth <= 3).
        skill_dirs = await _existing_skill_dirs(container)
        skill_dir = skill_dirs.get(skill_name)
        if not skill_dir:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"实例内不存在技能：{skill_name}",
            )

        # Docker archive API streams the folder as an in-memory tar whose
        # member names are rooted at the skill directory basename.
        tar = await container.get_archive(skill_dir)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                src = tar.extractfile(member)
                if src is None:
                    continue
                # Strip any leading "/" — zip entries must be relative.
                zf.writestr(member.name.lstrip("/"), src.read())
    finally:
        await docker.close()

    payload = buffer.getvalue()
    quoted = quote(skill_name)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{quoted}.zip"; '
                f"filename*=UTF-8''{quoted}.zip"
            ),
            "Content-Length": str(len(payload)),
        },
    )


# ─── Per-instance RAG / WebSearch plugin config ───────────────────────────────


class InstanceRagConfigUpdate(BaseModel):
    enabled: bool = True
    knowledge_ids: list[str] = Field(default_factory=list)
    knowledge_names: dict[str, str] | None = None


class InstanceWebSearchConfigUpdate(BaseModel):
    enabled: bool = True
    source_ids: list[str] = Field(default_factory=list)


@router.get(
    "/{instance_id}/rag-config",
    response_model=ApiResponse,
    summary="Read RAG plugin config for a NineClaw instance",
)
async def get_instance_rag_config(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    from app.services.hermes_dashboard_service import HermesError
    from app.services.instance_plugin_config_service import read_instance_rag_config

    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if (instance.actual_state or "").lower() != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"实例当前状态为 {instance.actual_state or 'unknown'}，必须运行中才能读取配置",
        )
    try:
        data = await read_instance_rag_config(instance_id)
    except HermesError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hermes {exc.status_code}: {exc.detail}",
        ) from exc
    except Exception as exc:
        logger.exception("read rag-config failed for %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=data)


@router.put(
    "/{instance_id}/rag-config",
    response_model=ApiResponse,
    summary="Update RAG plugin config for a NineClaw instance",
)
async def put_instance_rag_config(
    instance_id: str,
    body: InstanceRagConfigUpdate,
    svc: InstanceService = Depends(get_instance_service),
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
    docker_service: DockerService = Depends(get_docker_service),
) -> ApiResponse:
    from sqlalchemy import select

    from app.models.external_knowledge_config import ExternalKnowledgeConfig
    from app.services.hermes_dashboard_service import HermesError
    from app.services.instance_plugin_config_service import apply_instance_rag_config
    from app.services.knowledge_deploy_service import resolve_ragflow_credentials

    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if (instance.actual_state or "").lower() != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"实例当前状态为 {instance.actual_state or 'unknown'}，必须运行中才能保存配置",
        )

    ext_cfg = await session.scalar(
        select(ExternalKnowledgeConfig).where(ExternalKnowledgeConfig.tenant_id == tenant_id)
    )
    rag_base_url, rag_api_key = resolve_ragflow_credentials(
        base_url=ext_cfg.base_url if ext_cfg else None,
        api_key=ext_cfg.api_key if ext_cfg else None,
    )
    knowledge_names = {
        str(kid).strip(): str(name).strip()
        for kid, name in (body.knowledge_names or {}).items()
        if str(kid).strip() and isinstance(name, str) and str(name).strip()
    }

    try:
        data = await apply_instance_rag_config(
            instance_id,
            enabled=body.enabled,
            knowledge_ids=body.knowledge_ids,
            knowledge_name_map=knowledge_names or None,
            rag_base_url=rag_base_url,
            rag_api_key=rag_api_key,
            docker_service=docker_service,
            container_id=instance.container_id,
        )
    except HermesError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hermes {exc.status_code}: {exc.detail}",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("put rag-config failed for %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=data)


@router.get(
    "/{instance_id}/websearch-config",
    response_model=ApiResponse,
    summary="Read WebSearch plugin config for a NineClaw instance",
)
async def get_instance_websearch_config(
    instance_id: str,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    from app.services.hermes_dashboard_service import HermesError
    from app.services.instance_plugin_config_service import read_instance_websearch_config

    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if (instance.actual_state or "").lower() != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"实例当前状态为 {instance.actual_state or 'unknown'}，必须运行中才能读取配置",
        )
    try:
        data = await read_instance_websearch_config(instance_id)
    except HermesError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hermes {exc.status_code}: {exc.detail}",
        ) from exc
    except Exception as exc:
        logger.exception("read websearch-config failed for %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=data)


@router.put(
    "/{instance_id}/websearch-config",
    response_model=ApiResponse,
    summary="Update WebSearch plugin config for a NineClaw instance",
)
async def put_instance_websearch_config(
    instance_id: str,
    body: InstanceWebSearchConfigUpdate,
    svc: InstanceService = Depends(get_instance_service),
) -> ApiResponse:
    from app.services.hermes_dashboard_service import HermesError
    from app.services.instance_plugin_config_service import apply_instance_websearch_config

    try:
        instance = await svc.get_instance(instance_id, refresh=False)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if (instance.actual_state or "").lower() != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"实例当前状态为 {instance.actual_state or 'unknown'}，必须运行中才能保存配置",
        )

    async def _restart(iid: str) -> None:
        await svc.restart_instance(iid)

    try:
        data = await apply_instance_websearch_config(
            instance_id,
            enabled=body.enabled,
            source_ids=body.source_ids,
            restart_container=_restart,
        )
    except HermesError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hermes {exc.status_code}: {exc.detail}",
        ) from exc
    except DockerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_docker_terminal_error_detail(exc),
        ) from exc
    except Exception as exc:
        logger.exception("put websearch-config failed for %s", instance_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return ApiResponse(data=data)

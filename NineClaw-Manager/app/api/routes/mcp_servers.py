"""MCP Server API Routes.

RESTful CRUD for MCP (Model Context Protocol) servers, scoped per tenant via
the ``X-Tenant-ID`` header. Also provides SSE-streamed deployment and
health-check endpoints.

Routes:
- GET    /mcps              - List MCP servers for the tenant
- POST   /mcps              - Create an MCP server
- GET    /mcps/{id}         - Get an MCP server
- PUT    /mcps/{id}         - Update an MCP server
- DELETE /mcps/{id}         - Delete an MCP server
- POST   /mcps/deploy       - SSE stream deploy MCPs to instances
- GET    /mcps/health_check - SSE stream health probes for url-type MCPs
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.instance import ServiceInstance
from app.models.mcp_server import McpServer
from app.schemas.mcp_server import (
    McpDeployRequest,
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
    ToolCallRequest,
    ToolCallResponse,
    ToolStateUpdate,
)
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.hermes_gateway_service import GatewayError, HermesGatewayService
from app.services.instance_agent_snapshot import persist_manager_resource_snapshot
from app.services.mcp_tool_discovery import discover_tools as _discover_mcp_tools
from app.services.mcp_tool_invocation import call_tool
from app.services.nineclaw_bootstrap import (
    build_dashboard_base_url,
    build_gateway_base_url,
)

logger = logging.getLogger(__name__)

TENANT_HEADER = "X-Tenant-ID"
_GATEWAY_RESTART_TIMEOUT_SECONDS = 300.0
_MCP_RELOAD_TIMEOUT_SECONDS = 120.0
_ACTION_LOG_TAIL_LINES = 5

router = APIRouter(
    prefix="/mcps",
    tags=["mcps"],
)


class GatewayRestartError(Exception):
    """Raised when Hermes reports that gateway restart action failed."""


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    message: str = Field(default="success")
    data: Any = Field(default=None)


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    return x_tenant_id or settings.default_tenant_id


async def _get_owned(session: AsyncSession, mcp_id: UUID, tenant_id: str) -> McpServer:
    stmt = select(McpServer).where(
        McpServer.id == mcp_id, McpServer.tenant_id == tenant_id
    )
    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{mcp_id}' not found",
        )
    return obj


def _normalize_stdio_args(args: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for arg in args or []:
        text = str(arg).strip()
        if not text:
            continue
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = [text]
        normalized.extend(parts or [text])
    return normalized


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=ApiResponse, summary="List MCP servers")
async def list_mcp_servers(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    stmt = (
        select(McpServer)
        .where(McpServer.tenant_id == tenant_id)
        .order_by(McpServer.created_at.desc())
    )
    result = await session.execute(stmt)
    servers = result.scalars().all()
    items = [McpServerResponse.from_orm_mcp(s).model_dump(mode="json") for s in servers]
    return ApiResponse(data={"items": items, "total": len(items)})


@router.post(
    "",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an MCP server",
)
async def create_mcp_server(
    body: McpServerCreate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    existing_stmt = select(McpServer).where(
        McpServer.tenant_id == tenant_id, McpServer.name == body.name.strip()
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"MCP server with name '{body.name}' already exists",
        )

    server = McpServer(
        tenant_id=tenant_id,
        name=body.name.strip(),
        description=body.description.strip(),
        transport=body.transport,
        command=body.command.strip() if body.transport == "stdio" else "",
        args=_normalize_stdio_args(body.args) if body.transport == "stdio" else [],
        env=body.env if body.transport == "stdio" else {},
        url=body.url.strip() if body.transport == "url" else "",
        headers=body.headers if body.transport == "url" else {},
        timeout=body.timeout,
        connect_timeout=body.connect_timeout,
        enabled=body.enabled,
    )
    session.add(server)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.exception("Failed to insert MCP server")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create MCP server: {exc.orig}",
        ) from exc
    await session.refresh(server)
    return ApiResponse(
        data=McpServerResponse.from_orm_mcp(server).model_dump(mode="json")
    )


@router.get("/{mcp_id}", response_model=ApiResponse, summary="Get an MCP server")
async def get_mcp_server(
    mcp_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)
    return ApiResponse(
        data=McpServerResponse.from_orm_mcp(server).model_dump(mode="json")
    )


@router.put("/{mcp_id}", response_model=ApiResponse, summary="Update an MCP server")
async def update_mcp_server(
    mcp_id: UUID,
    body: McpServerUpdate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)

    if body.name is not None and body.name.strip() != server.name:
        new_name = body.name.strip()
        clash_stmt = select(McpServer).where(
            McpServer.tenant_id == tenant_id,
            McpServer.name == new_name,
            McpServer.id != mcp_id,
        )
        if (await session.execute(clash_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"MCP server with name '{new_name}' already exists",
            )
        server.name = new_name

    if body.description is not None:
        server.description = body.description.strip()

    # transport switch — clear fields for the old type, fill for the new
    if body.transport is not None and body.transport != server.transport:
        new_transport = body.transport
        if new_transport == "url":
            server.command = ""
            server.args = []
            server.env = {}
            if body.url is not None:
                server.url = body.url.strip()
            if body.headers is not None:
                server.headers = body.headers
        elif new_transport == "stdio":
            server.url = ""
            server.headers = {}
            if body.command is not None:
                server.command = body.command.strip()
            if body.args is not None:
                server.args = _normalize_stdio_args(body.args)
            if body.env is not None:
                server.env = body.env
        server.transport = new_transport
    else:
        # No transport switch — update individual fields
        if body.command is not None:
            server.command = body.command.strip()
        if body.args is not None:
            server.args = _normalize_stdio_args(body.args)
        if body.env is not None:
            server.env = body.env
        if body.url is not None:
            server.url = body.url.strip()
        if body.headers is not None:
            server.headers = body.headers

    if body.timeout is not None:
        server.timeout = body.timeout
    if body.connect_timeout is not None:
        server.connect_timeout = body.connect_timeout
    if body.enabled is not None:
        server.enabled = body.enabled

    from app.models.mcp_server import _utcnow

    server.updated_at = _utcnow()

    session.add(server)
    await session.commit()
    await session.refresh(server)
    return ApiResponse(
        data=McpServerResponse.from_orm_mcp(server).model_dump(mode="json")
    )


@router.delete("/{mcp_id}", response_model=ApiResponse, summary="Delete an MCP server")
async def delete_mcp_server(
    mcp_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)
    await session.delete(server)
    await session.commit()
    return ApiResponse(data={"deleted": str(mcp_id)})


# ─── Tool management ────────────────────────────────────────────────────────


def _enrich_tools_with_settings(tools: list[dict], settings: dict) -> list[dict]:
    """Merge discovery results with user settings."""
    result = []
    for tool in tools:
        name = tool["name"]
        enabled = settings.get(name, True)
        result.append({**tool, "enabled": enabled})
    return result


def _merge_discovered_tool_settings(
    current_settings: dict | None, tools: list[dict]
) -> dict:
    """Return tool settings with newly discovered tools enabled by default."""
    settings = dict(current_settings or {})
    for tool in tools:
        if tool["name"] not in settings:
            settings[tool["name"]] = True
    return settings


def _set_tool_enabled(
    current_settings: dict | None, tool_name: str, enabled: bool
) -> dict:
    """Return a fresh tool settings dict with one tool state updated."""
    settings = dict(current_settings or {})
    settings[tool_name] = enabled
    return settings


@router.post(
    "/{mcp_id}/discover-tools",
    response_model=ApiResponse,
    summary="Discover tools from an MCP server",
)
async def discover_tools_endpoint(
    mcp_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)

    kwargs: dict[str, Any] = {}
    if server.transport == "stdio":
        kwargs = {"command": server.command, "args": server.args, "env": server.env}
    else:
        kwargs = {"url": server.url, "headers": server.headers}

    tools, error = await _discover_mcp_tools(server.transport, **kwargs)

    # Only update cached tools on success; preserve existing cache on failure
    if error is None:
        server.tools = tools
    server.tools_error = error
    server.tools_discovered_at = _utcnow_dt()

    # Initialize settings for newly discovered tools (default enabled).
    # Assign a fresh dict so SQLAlchemy tracks JSON/JSONB changes reliably.
    server.tool_settings = _merge_discovered_tool_settings(
        server.tool_settings,
        tools,
    )

    session.add(server)
    await session.commit()
    await session.refresh(server)

    return ApiResponse(
        data={
            "tools": _enrich_tools_with_settings(tools, server.tool_settings),
            "error": error,
            "discovered_at": server.tools_discovered_at,
        }
    )


@router.get(
    "/{mcp_id}/tools",
    response_model=ApiResponse,
    summary="Get cached tools for an MCP server",
)
async def get_mcp_tools(
    mcp_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)
    tools = server.tools or []
    return ApiResponse(
        data={
            "tools": _enrich_tools_with_settings(tools, server.tool_settings or {}),
            "discovered_at": server.tools_discovered_at,
            "error": server.tools_error,
        }
    )


@router.put(
    "/{mcp_id}/tools/{tool_name}",
    response_model=ApiResponse,
    summary="Update a single tool's enabled state",
)
async def update_tool_state(
    mcp_id: UUID,
    tool_name: str,
    body: ToolStateUpdate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)

    # Validate tool exists in discovered tools list
    known_tools = {t["name"] for t in (server.tools or [])}
    if tool_name not in known_tools:
        raise HTTPException(status_code=404, detail="工具不存在，请先发现工具")

    # Assign a fresh dict so SQLAlchemy persists JSON/JSONB updates. Mutating
    # the existing dict in place is not reliably detected for plain JSON fields.
    server.tool_settings = _set_tool_enabled(
        server.tool_settings,
        tool_name,
        body.enabled,
    )

    session.add(server)
    await session.commit()

    return ApiResponse(data={"tool_name": tool_name, "enabled": body.enabled})


@router.post(
    "/{mcp_id}/call-tool",
    response_model=ApiResponse,
    summary="Call a tool on an MCP server",
)
async def call_tool_endpoint(
    mcp_id: UUID,
    body: ToolCallRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    server = await _get_owned(session, mcp_id, tenant_id)

    # Validate tool exists in discovered tools list
    known_tools = {t["name"] for t in (server.tools or [])}
    if known_tools and body.tool_name not in known_tools:
        raise HTTPException(status_code=404, detail="工具不存在，请先发现工具")

    kwargs: dict[str, Any] = {}
    if server.transport == "stdio":
        kwargs = {"command": server.command, "args": server.args, "env": server.env}
    else:
        kwargs = {"url": server.url, "headers": server.headers}

    content, is_error, duration_ms = await call_tool(
        transport=server.transport,
        tool_name=body.tool_name,
        arguments=body.arguments,
        **kwargs,
    )

    return ApiResponse(
        data=ToolCallResponse(
            content=content,
            is_error=is_error,
            duration_ms=duration_ms,
        ).model_dump(mode="json")
    )


# ─── Refresh (health + tools) ────────────────────────────────────────────────

_REFRESH_CONCURRENCY = 5


@router.post("/refresh", summary="Refresh health and tools for all MCP servers")
async def refresh_all_mcp_servers(
    tenant_id: str = Depends(get_tenant_id),
):
    """Concurrently probe health (url-type only) and discover tools for every
    MCP server belonging to the current tenant.  Results are streamed as SSE
    events and persisted to the database.
    """
    async with async_session_maker() as session:
        stmt = select(McpServer).where(McpServer.tenant_id == tenant_id)
        rows = list((await session.execute(stmt)).scalars().all())

    # Snapshot the data we need so the session can be closed.
    snapshots: list[dict[str, Any]] = []
    for s in rows:
        snapshots.append(
            {
                "id": s.id,
                "name": s.name,
                "transport": s.transport,
                "url": s.url,
                "headers": s.headers,
                "command": s.command,
                "args": s.args,
                "env": s.env,
                "tool_settings": dict(s.tool_settings) if s.tool_settings else {},
            }
        )

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        if not snapshots:
            yield {"event": "done", "data": json.dumps({"checked": 0})}
            return

        sem = asyncio.Semaphore(_REFRESH_CONCURRENCY)
        queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        _DONE = object()

        async def _refresh_one(snap: dict[str, Any]) -> None:
            async with sem:
                mcp_id = snap["id"]
                name = snap["name"]
                transport = snap["transport"]

                # --- Health check ---
                if transport == "url" and snap["url"]:
                    health_status, _ = await _probe_url_mcp_health(snap["url"])
                else:
                    health_status = "skipped"

                # --- Tool discovery ---
                kwargs: dict[str, Any] = {}
                if transport == "stdio":
                    kwargs = {
                        "command": snap["command"],
                        "args": snap["args"],
                        "env": snap["env"],
                    }
                else:
                    kwargs = {"url": snap["url"], "headers": snap["headers"]}

                tools, tools_error = await _discover_mcp_tools(transport, **kwargs)
                discovered_at = _utcnow_iso()

                await queue.put(
                    {
                        "mcp_id": mcp_id,
                        "name": name,
                        "health_status": health_status,
                        "tools": tools,
                        "tools_error": tools_error,
                        "discovered_at": discovered_at,
                        "tool_settings": snap["tool_settings"],
                    }
                )

        async def coordinator() -> None:
            await asyncio.gather(
                *(_refresh_one(s) for s in snapshots),
                return_exceptions=True,
            )
            await queue.put(_DONE)

        coord_task = asyncio.create_task(coordinator())

        results: list[dict[str, Any]] = []
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                results.append(item)

                # Build enriched tools for the SSE payload
                enriched = _enrich_tools_with_settings(
                    item["tools"], item["tool_settings"]
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "mcp_id": str(item["mcp_id"]),
                            "name": item["name"],
                            "health_status": item["health_status"],
                            "tools": enriched,
                            "tools_error": item["tools_error"],
                            "discovered_at": item["discovered_at"],
                        }
                    ),
                }
        finally:
            await coord_task

        # Persist results in a single batch.
        if results:
            try:
                async with async_session_maker() as session:
                    for r in results:
                        checked_at_dt = datetime.fromisoformat(
                            r["discovered_at"]
                        ).replace(tzinfo=None)

                        values: dict[str, Any] = {
                            "tools_error": r["tools_error"],
                            "tools_discovered_at": checked_at_dt,
                        }

                        # Only persist health status for url-type (stdio = "skipped")
                        if r["health_status"] != "skipped":
                            values["last_health_status"] = r["health_status"]
                            values["last_checked_at"] = checked_at_dt

                        # Only update cached tools on success
                        if r["tools_error"] is None:
                            values["tools"] = r["tools"]

                        # Initialize settings for newly discovered tools
                        existing_settings = dict(r["tool_settings"])
                        if r["tools_error"] is None:
                            for tool in r["tools"]:
                                if tool["name"] not in existing_settings:
                                    existing_settings[tool["name"]] = True
                            values["tool_settings"] = existing_settings

                        await session.execute(
                            McpServer.__table__.update()
                            .where(McpServer.id == r["mcp_id"])
                            .values(**values)
                        )
                    await session.commit()
            except Exception:
                logger.exception("Failed to persist MCP refresh results")

        yield {"event": "done", "data": json.dumps({"checked": len(results)})}

    return EventSourceResponse(event_stream())


# ─── Deploy ──────────────────────────────────────────────────────────────────


def _is_sse_url(url: str | None) -> bool:
    """Detect legacy SSE MCP endpoints whose URL path ends with ``/sse``.

    Hermes connects url-type MCP servers with the streamable-HTTP transport
    by default; legacy SSE servers must be declared with ``transport: sse``.
    Query strings and trailing slashes are ignored.
    """
    if not url:
        return False
    path = url.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.lower().endswith("/sse")


def _build_hermes_mcp_entry(
    server: McpServer, tools_override: list[str] | None = None
) -> dict[str, Any]:
    """Convert a McpServer ORM object into a Hermes mcp_servers entry.

    Hermes config format:
      stdio: {command, args, env?, timeout?, connect_timeout?, enabled?}
      url:   {url, headers?, timeout?, connect_timeout?, enabled?, transport?}
    """
    entry: dict[str, Any] = {}

    if server.transport == "stdio":
        entry["command"] = server.command
        entry["args"] = _normalize_stdio_args(server.args)
        if server.env:
            entry["env"] = dict(server.env)
    elif server.transport == "url":
        entry["url"] = server.url
        if server.headers:
            entry["headers"] = dict(server.headers)
        entry["sampling"] = {"enabled": False}
        if _is_sse_url(server.url):
            entry["transport"] = "sse"

    if server.timeout is not None:
        entry["timeout"] = server.timeout
    if server.connect_timeout is not None:
        entry["connect_timeout"] = server.connect_timeout
    if not server.enabled:
        entry["enabled"] = False

    # Tool filtering
    if tools_override is not None:
        all_tool_names = [t["name"] for t in (server.tools or [])]
        excluded = [n for n in all_tool_names if n not in tools_override]
        if excluded:
            entry["tools"] = {"exclude": excluded}
    elif server.tool_settings:
        known_names = {t["name"] for t in (server.tools or [])}
        excluded = [
            n
            for n, enabled in server.tool_settings.items()
            if not enabled and n in known_names
        ]
        if excluded:
            entry["tools"] = {"exclude": excluded}

    return entry


def _merge_hermes_mcp_servers(
    existing_servers: Any,
    new_entries: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    existing = existing_servers if isinstance(existing_servers, dict) else {}
    merged = dict(existing)
    updated: list[str] = []
    for name, entry in new_entries.items():
        if name in merged:
            updated.append(name)
        merged[name] = entry
    return merged, updated


def _format_gateway_restart_failure(
    action_name: str, action_status: dict[str, Any]
) -> str:
    exit_code = action_status.get("exit_code")
    lines = action_status.get("lines")
    tail = ""
    if isinstance(lines, list):
        clean_lines = [str(line).strip() for line in lines if str(line).strip()]
        if clean_lines:
            tail = "；日志: " + " | ".join(clean_lines[-_ACTION_LOG_TAIL_LINES:])
    return f"Gateway 重启失败 ({action_name}, exit_code={exit_code}){tail}"


async def _reload_mcp_with_restart_fallback(
    *,
    instance_id: str,
    api_key: str,
    dashboard: HermesService,
) -> str:
    """Hot-reload MCP in Gateway, falling back for older Runtime images."""
    try:
        async with HermesGatewayService(
            base_url=build_gateway_base_url(instance_id),
            api_key=api_key,
            timeout=_MCP_RELOAD_TIMEOUT_SECONDS,
        ) as gateway:
            await gateway.reload_mcp()
        return "hot_reload"
    except (GatewayError, httpx.RequestError, asyncio.TimeoutError) as exc:
        logger.warning(
            "deploy mcp: hot reload unavailable for %s; falling back to "
            "gateway restart: %s",
            instance_id,
            exc,
        )

    restart_result = await dashboard.restart_gateway()
    action_name = "gateway-restart"
    if isinstance(restart_result, dict) and restart_result.get("name"):
        action_name = str(restart_result["name"])
    action_status = await dashboard.wait_action_finished(
        action_name,
        timeout=_GATEWAY_RESTART_TIMEOUT_SECONDS,
    )
    if isinstance(action_status, dict) and action_status.get("exit_code") not in (
        0,
        None,
    ):
        raise GatewayRestartError(
            _format_gateway_restart_failure(action_name, action_status)
        )
    return "gateway_restart"


@router.post(
    "/deploy",
    summary="Stream deployment of selected MCP servers to NineClaw instances",
)
async def deploy_mcp_servers(
    body: McpDeployRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Push selected MCP servers into each target nineclaw instance's
    ``mcp_servers`` config block, streaming progress via SSE.

    Merge strategy: selected MCP names overwrite the same names on the
    target instance. Other existing mcp_servers are preserved.
    """
    # Validate ownership before SSE stream starts.
    async with async_session_maker() as session:
        mcp_stmt = select(McpServer).where(
            McpServer.tenant_id == tenant_id,
            McpServer.id.in_(body.mcp_ids),
        )
        mcps = list((await session.execute(mcp_stmt)).scalars().all())
        if len(mcps) != len(set(body.mcp_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分 MCP 不存在或不属于当前租户",
            )

        inst_stmt = select(ServiceInstance).where(
            ServiceInstance.tenant_id == tenant_id,
            ServiceInstance.id.in_(body.instance_ids),
        )
        instances = list((await session.execute(inst_stmt)).scalars().all())
        if len(instances) != len(set(body.instance_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分实例不存在或不属于当前租户",
            )

    # Preserve user order, deduplicate.
    by_id = {m.id: m for m in mcps}
    ordered_mcps = [by_id[mid] for mid in body.mcp_ids if mid in by_id]
    inst_by_id = {i.id: i for i in instances}
    seen_inst: set[str] = set()
    ordered_instances: list[Any] = []
    for iid in body.instance_ids:
        if iid not in seen_inst and iid in inst_by_id:
            seen_inst.add(iid)
            ordered_instances.append(inst_by_id[iid])

    # Build a lookup from tools_config
    tools_config_map: dict[str, list[str]] = {}
    if body.tools_config:
        for tc in body.tools_config:
            tools_config_map[str(tc.mcp_id)] = tc.enabled_tools

    # Build entries once — every instance receives the same set.
    new_entries: dict[str, dict[str, Any]] = {}
    for mcp in ordered_mcps:
        override = tools_config_map.get(str(mcp.id))
        new_entries[mcp.name] = _build_hermes_mcp_entry(mcp, tools_override=override)

    api_key = settings.nineclaw_token

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        # Initial pending snapshot.
        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "pending",
                        "error": None,
                    }
                ),
            }

        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "deploying",
                        "error": None,
                    }
                ),
            }

            actual = (inst.actual_state or "").lower()
            if actual != "running":
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": (
                                f"实例当前状态为 {actual or 'unknown'}，"
                                "必须运行中才能部署"
                            ),
                        }
                    ),
                }
                continue

            base_url = build_dashboard_base_url(inst.id)
            try:
                async with HermesService(base_url=base_url, api_key=api_key) as svc:
                    current = await svc.get_config()
                    if not isinstance(current, dict):
                        current = {}

                    merged, updated = _merge_hermes_mcp_servers(
                        current.get("mcp_servers", {}),
                        new_entries,
                    )

                    current["mcp_servers"] = merged
                    await svc.put_config(current)
                    reload_mode = await _reload_mcp_with_restart_fallback(
                        instance_id=inst.id,
                        api_key=api_key,
                        dashboard=svc,
                    )
                async with async_session_maker() as snapshot_session:
                    await persist_manager_resource_snapshot(
                        snapshot_session,
                        tenant_id=tenant_id,
                        instance_id=inst.id,
                        mcps=[
                            {
                                "id": str(mcp.id),
                                "name": mcp.name,
                                "enabled": bool(mcp.enabled),
                            }
                            for mcp in ordered_mcps
                        ],
                    )
                    await snapshot_session.commit()

            except HermesError as exc:
                logger.warning(
                    "deploy mcp: hermes error for %s: %s", inst.id, exc.detail
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": f"Hermes {exc.status_code}: {exc.detail}",
                        }
                    ),
                }
                continue
            except TimeoutError as exc:
                logger.warning(
                    "deploy mcp: gateway restart timeout for %s: %s", inst.id, exc
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": (
                                "Gateway 重启超时，后台可能仍在继续。"
                                "请稍后查看实例状态后重试"
                            ),
                        }
                    ),
                }
                continue
            except GatewayRestartError as exc:
                logger.warning(
                    "deploy mcp: gateway restart failed for %s: %s", inst.id, exc
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": str(exc),
                        }
                    ),
                }
                continue
            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                logger.warning("deploy mcp: connection error for %s: %s", inst.id, exc)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": f"无法连接实例: {exc.__class__.__name__}",
                        }
                    ),
                }
                continue
            except Exception as exc:  # pragma: no cover
                logger.exception("deploy mcp: unexpected error for %s", inst.id)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": str(exc),
                        }
                    ),
                }
                continue

            result_data: dict[str, Any] = {
                "instance_id": inst.id,
                "name": inst.name,
                "status": "deployed",
                "error": None,
                "reload_mode": reload_mode,
            }
            if updated:
                result_data["updated"] = updated
            yield {
                "event": "status",
                "data": json.dumps(result_data),
            }

        yield {"event": "done", "data": json.dumps({"finished": True})}

    return EventSourceResponse(event_stream())


# ─── Health check ────────────────────────────────────────────────────────────


_HEALTH_TIMEOUT_SECONDS = 5.0
_HEALTH_CONCURRENCY = 10
_RESPONSE_TEXT_MAX = 500


async def _probe_url_mcp_health(url_str: str) -> tuple[str, str]:
    """Best-effort health probe for a url-type MCP server endpoint.

    Tries ``{base}/health`` first (common for vLLM, litellm-proxy, etc.)
    and falls back to ``{base}/`` if needed. Returns (status, response_text).

    Status mapping:
      HTTP 200 or 401 → online
      other HTTP codes → abnormal
      timeout / connection error → offline
    """
    base = url_str.rstrip("/")
    # Try /health endpoint first.
    health_url = f"{base}/health"
    try:
        async with httpx.AsyncClient(
            timeout=_HEALTH_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp = await client.get(health_url)
        body = (resp.text or "")[:_RESPONSE_TEXT_MAX]
        if resp.status_code in (200, 401):
            return "online", f"HTTP {resp.status_code} {health_url}\n{body}"
        # /health didn't work — try the base URL.
        resp2 = await client.get(base)
        body2 = (resp2.text or "")[:_RESPONSE_TEXT_MAX]
        if resp2.status_code in (200, 401):
            return "online", f"HTTP {resp2.status_code} {base}\n{body2}"
        return (
            "abnormal",
            f"HTTP {resp.status_code} {health_url}\n{body}",
        )
    except httpx.TimeoutException as exc:
        return (
            "offline",
            f"timeout {_HEALTH_TIMEOUT_SECONDS:g}s {health_url} ({exc.__class__.__name__})",
        )
    except Exception as exc:
        return ("offline", f"{exc.__class__.__name__}: {exc}"[:_RESPONSE_TEXT_MAX])


@router.get(
    "/health_check",
    summary="Stream concurrent health probes for MCP servers",
)
async def health_check_stream(
    tenant_id: str = Depends(get_tenant_id),
):
    """Run health probes for url-type MCP servers (stdio type always
    returns ``unknown``) and stream results as SSE.

    Probes run concurrently (bounded by ``_HEALTH_CONCURRENCY``).
    Results are persisted to ``last_health_status`` and
    ``last_checked_at`` in a single batch after the stream completes.
    """
    async with async_session_maker() as session:
        stmt = select(McpServer).where(McpServer.tenant_id == tenant_id)
        rows = list((await session.execute(stmt)).scalars().all())

    targets: list[tuple[UUID, str, str]] = [(p.id, p.transport, p.url) for p in rows]

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        if not targets:
            yield {"event": "done", "data": json.dumps({"checked": 0})}
            return

        sem = asyncio.Semaphore(_HEALTH_CONCURRENCY)
        queue: asyncio.Queue[tuple[UUID, str, str, str] | object] = asyncio.Queue()
        _DONE = object()

        async def check_one(pid: UUID, transport: str, url_str: str) -> None:
            async with sem:
                if transport == "url" and url_str:
                    status_str, response_text = await _probe_url_mcp_health(url_str)
                else:
                    status_str = "unknown"
                    response_text = "stdio MCP — cannot probe remotely"
                checked_at = _utcnow_iso()
                await queue.put((pid, status_str, response_text, checked_at))

        async def coordinator() -> None:
            await asyncio.gather(
                *(check_one(pid, t, u) for pid, t, u in targets),
                return_exceptions=True,
            )
            await queue.put(_DONE)

        coord_task = asyncio.create_task(coordinator())

        results: list[tuple[UUID, str, str]] = []
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                pid, status_str, response_text, checked_at = item
                results.append((pid, status_str, checked_at))
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "mcp_id": str(pid),
                            "status": status_str,
                            "checked_at": checked_at,
                            "response_text": response_text,
                        }
                    ),
                }
        finally:
            await coord_task

        if results:
            try:
                async with async_session_maker() as session:
                    for pid, status_str, checked_at in results:
                        await session.execute(
                            McpServer.__table__.update()
                            .where(McpServer.id == pid)
                            .values(
                                last_health_status=status_str,
                                last_checked_at=datetime.fromisoformat(
                                    checked_at
                                ).replace(tzinfo=None),
                            )
                        )
                    await session.commit()
            except Exception:
                logger.exception("Failed to persist MCP health-check results")

        yield {"event": "done", "data": json.dumps({"checked": len(results)})}

    return EventSourceResponse(event_stream())


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _utcnow_dt():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)

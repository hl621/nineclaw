"""Settings API — knowledge backend configuration."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

import asyncssh
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.external_knowledge_config import ExternalKnowledgeConfig
from app.models.remote_docker_config import RemoteDockerConfig
from app.services import knowledge_factory
from app.services.docker_client import (
    build_ssh_docker_url,
    create_docker_client,
    mask_docker_url,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class KnowledgeBackendOut(BaseModel):
    backend: str
    base_url: str
    has_api_key: bool
    api_key_masked: str = ""


def _mask_key(key: str) -> str:
    if not key:
        return ""
    # e.g. "ragflow-F_StCg****stXU"
    prefix = key[:10]
    suffix = key[-4:]
    return f"{prefix}****{suffix}"


class KnowledgeBackendIn(BaseModel):
    backend: str
    base_url: str
    api_key: str = ""


def _std(code: int = 0, data=None, message: str = "success") -> dict:
    return {"code": code, "message": message, "data": data}


class KnowledgeBackendTestIn(BaseModel):
    base_url: str
    api_key: str = ""  # optional override; empty = use saved key


class RemoteDockerOut(BaseModel):
    enabled: bool
    ssh_host: str
    ssh_port: int
    ssh_username: str
    has_password: bool


class RemoteDockerIn(BaseModel):
    enabled: bool = False
    ssh_host: str = Field(default="", max_length=255)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str = Field(default="", max_length=255)
    ssh_password: str = Field(default="", max_length=1024)


class RemoteDockerTestIn(RemoteDockerIn):
    pass


def _remote_docker_out(row: RemoteDockerConfig | None) -> RemoteDockerOut:
    if row is None:
        return RemoteDockerOut(
            enabled=False,
            ssh_host="",
            ssh_port=22,
            ssh_username="",
            has_password=False,
        )

    return RemoteDockerOut(
        enabled=row.enabled,
        ssh_host=row.ssh_host,
        ssh_port=row.ssh_port,
        ssh_username=row.ssh_username,
        has_password=bool(row.ssh_password),
    )


def _validate_remote_docker_host(host: str) -> str:
    value = host.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="远程 Docker 主机不能为空",
        )

    if value.lower() == "localhost":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="远程 Docker 主机不能使用 localhost，请填写宿主机或远程机器的真实 IP/域名",
        )

    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return value

    if ip.is_loopback:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="远程 Docker 主机不能使用回环地址，请填写宿主机或远程机器的真实 IP/域名",
        )
    return value


def _validate_remote_docker_username(username: str) -> str:
    value = username.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="远程 Docker SSH 账号不能为空",
        )
    return value


async def _preflight_remote_docker(
    *, host: str, port: int, username: str, password: str
) -> tuple[bool, str, dict]:
    """Check SSH and Docker CLI access before opening the Docker API tunnel."""
    try:
        async with asyncssh.connect(
            host=host,
            port=port,
            username=username,
            password=password or None,
            known_hosts=None,
            env={"USER": username, "LOGNAME": username},
        ) as conn:
            which = await conn.run("command -v docker", check=False)
            if which.exit_status != 0:
                return (
                    False,
                    "SSH 登录成功，但远端非交互环境找不到 docker 命令。请在远端安装 Docker CLI，"
                    "或把 docker 所在目录加入 SSH 非交互 PATH。可在远端执行 `command -v docker` 检查。",
                    {"ok": False, "stage": "docker_cli"},
                )

            version = await conn.run(
                "docker version --format '{{.Server.Version}}|{{.Server.APIVersion}}'",
                check=False,
            )
            if version.exit_status != 0:
                stderr = (version.stderr or version.stdout or "").strip()
                return (
                    False,
                    "SSH 登录成功，但该账号不能访问远端 Docker Engine。请确认用户已加入 docker 组，"
                    "或远端 Docker daemon 正在运行。"
                    + (f" 远端返回：{stderr}" if stderr else ""),
                    {"ok": False, "stage": "docker_daemon"},
                )

            server_version, _, api_version = version.stdout.strip().partition("|")
            return (
                True,
                "",
                {
                    "ok": True,
                    "version": server_version or None,
                    "api_version": api_version or None,
                },
            )
    except Exception as exc:
        message = str(exc)
        if password:
            message = message.replace(password, "********")
        return (
            False,
            f"SSH 连接远端 Docker 主机失败：{message}",
            {"ok": False, "stage": "ssh"},
        )


@router.post("/knowledge-backend/test")
async def test_knowledge_backend(
    body: KnowledgeBackendTestIn,
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    base_url = body.base_url.rstrip("/")

    # Resolve api_key: body override > DB
    api_key = body.api_key
    if not api_key:
        row = await session.scalar(
            select(ExternalKnowledgeConfig).where(
                ExternalKnowledgeConfig.tenant_id == x_tenant_id
            )
        )
        api_key = row.api_key if row else ""

    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
            resp = await client.get(
                f"{base_url}/api/v1/datasets",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
        if resp.status_code < 400:
            return _std(data={"ok": True, "status": resp.status_code})
        return _std(code=1, message=f"HTTP {resp.status_code}", data={"ok": False})
    except Exception as exc:
        message = str(exc)
        if api_key:
            message = message.replace(api_key, _mask_key(api_key))
        return _std(code=1, message=message, data={"ok": False})


@router.get("/knowledge-backend")
async def get_knowledge_backend(
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(
        select(ExternalKnowledgeConfig).where(
            ExternalKnowledgeConfig.tenant_id == x_tenant_id
        )
    )
    if row is None:
        return _std(
            data=KnowledgeBackendOut(
                backend=settings.knowledge_backend,
                base_url="",
                has_api_key=False,
                api_key_masked="",
            )
        )
    return _std(
        data=KnowledgeBackendOut(
            backend=row.backend,
            base_url=row.base_url,
            has_api_key=bool(row.api_key),
            api_key_masked=_mask_key(row.api_key),
        )
    )


@router.put("/knowledge-backend")
async def put_knowledge_backend(
    body: KnowledgeBackendIn,
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(
        select(ExternalKnowledgeConfig).where(
            ExternalKnowledgeConfig.tenant_id == x_tenant_id
        )
    )
    if row is None:
        row = ExternalKnowledgeConfig(tenant_id=x_tenant_id)
        session.add(row)

    row.backend = body.backend
    row.base_url = body.base_url
    if body.api_key:  # empty string = keep existing
        row.api_key = body.api_key
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await session.commit()

    return _std(
        data=KnowledgeBackendOut(
            backend=row.backend,
            base_url=row.base_url,
            has_api_key=bool(row.api_key),
            api_key_masked=_mask_key(row.api_key),
        )
    )


@router.get("/remote-docker")
async def get_remote_docker(
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(
        select(RemoteDockerConfig).where(RemoteDockerConfig.tenant_id == x_tenant_id)
    )
    return _std(data=_remote_docker_out(row))


@router.put("/remote-docker")
async def put_remote_docker(
    body: RemoteDockerIn,
    request: Request,
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    row = await session.scalar(
        select(RemoteDockerConfig).where(RemoteDockerConfig.tenant_id == x_tenant_id)
    )
    if row is None:
        row = RemoteDockerConfig(tenant_id=x_tenant_id)
        session.add(row)

    row.enabled = body.enabled
    row.ssh_host = (
        _validate_remote_docker_host(body.ssh_host)
        if body.enabled
        else body.ssh_host.strip()
    )
    row.ssh_port = body.ssh_port
    row.ssh_username = (
        _validate_remote_docker_username(body.ssh_username)
        if body.enabled
        else body.ssh_username.strip()
    )
    if body.ssh_password:
        row.ssh_password = body.ssh_password
    if body.enabled:
        ok, message, preflight_data = await _preflight_remote_docker(
            host=row.ssh_host,
            port=row.ssh_port,
            username=row.ssh_username,
            password=row.ssh_password,
        )
        if not ok:
            return _std(code=1, message=message, data=preflight_data)
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await session.commit()
    await session.refresh(row)

    docker_service = getattr(request.app.state, "docker_service", None)
    if docker_service is not None:
        try:
            await docker_service.close()
            await docker_service.connect()
        except Exception as exc:
            message = str(exc)
            if "Server disconnected" in message:
                message = (
                    "远程 Docker 预检通过，但 Docker API 隧道断开。"
                    "请确认远端 Docker CLI 支持 `docker system dial-stdio`，并且该命令在 SSH 非交互环境可执行。"
                )
            return _std(code=1, message=message, data={"ok": False})

    return _std(data=_remote_docker_out(row))


@router.post("/remote-docker/test")
async def test_remote_docker(
    body: RemoteDockerTestIn,
    x_tenant_id: str = Header(default=settings.default_tenant_id, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
):
    if not body.enabled:
        docker_url = settings.resolved_docker_url
        try:
            docker = create_docker_client(docker_url=docker_url)
            try:
                version = await docker.version()
            finally:
                await docker.close()
            return _std(
                data={
                    "ok": True,
                    "version": version.get("Version"),
                    "api_version": version.get("ApiVersion"),
                }
            )
        except Exception as exc:
            message = str(exc).replace(docker_url, mask_docker_url(docker_url))
            return _std(code=1, message=message, data={"ok": False})

    password = body.ssh_password
    host = _validate_remote_docker_host(body.ssh_host)
    username = _validate_remote_docker_username(body.ssh_username)
    if not password:
        row = await session.scalar(
            select(RemoteDockerConfig).where(
                RemoteDockerConfig.tenant_id == x_tenant_id
            )
        )
        password = row.ssh_password if row else ""

    docker_url = build_ssh_docker_url(
        username=username,
        password=password,
        host=host,
        port=body.ssh_port,
    )

    try:
        ok, message, preflight_data = await _preflight_remote_docker(
            host=host,
            port=body.ssh_port,
            username=username,
            password=password,
        )
        if not ok:
            return _std(code=1, message=message, data=preflight_data)

        docker = create_docker_client(
            docker_url=docker_url,
            strict_ssh_host_keys=False,
        )
        try:
            version = await docker.version()
        finally:
            await docker.close()
        return _std(
            data={
                "ok": True,
                "version": version.get("Version") or preflight_data.get("version"),
                "api_version": version.get("ApiVersion")
                or preflight_data.get("api_version"),
            }
        )
    except Exception as exc:
        message = str(exc).replace(docker_url, mask_docker_url(docker_url))
        if "Server disconnected" in message and docker_url.startswith("ssh://"):
            message = (
                "SSH 登录和 Docker CLI 预检通过，但 Docker API 隧道断开。"
                "请确认远端 Docker CLI 支持 `docker system dial-stdio`，并且该命令在 SSH 非交互环境可执行。"
            )
        return _std(code=1, message=message, data={"ok": False})

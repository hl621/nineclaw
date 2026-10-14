"""Docker client construction helpers."""

from __future__ import annotations

import asyncio
import ssl
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

# Belt-and-suspenders: ensure Proactor on Windows before aiodocker/aiohttp imports.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import aiodocker
from aiodocker.ssh import SSHConnector
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.remote_docker_config import RemoteDockerConfig
from app.services.windows_ssh_docker import WindowsSSHDockerConnector


def build_ssh_docker_url(
    *, username: str, password: str, host: str, port: int = 22
) -> str:
    """Build an SSH Docker URL, URL-encoding credentials safely."""
    encoded_user = quote(username.strip(), safe="")
    encoded_password = quote(password, safe="")
    credentials = encoded_user
    if encoded_password:
        credentials = f"{encoded_user}:{encoded_password}"
    return f"ssh://{credentials}@{host.strip()}:{port}"


def create_docker_client(
    docker_url: str | None = None,
    *,
    strict_ssh_host_keys: bool = True,
) -> aiodocker.Docker:
    """Create a Docker client from the configured Docker Engine endpoint."""
    docker_url = docker_url or settings.resolved_docker_url
    ssl_context = _docker_ssl_context()
    if ssl_context is not None and docker_url.startswith("tcp://"):
        docker_url = docker_url.replace("tcp://", "https://", 1)

    if docker_url.startswith("ssh://"):
        # aiodocker SSHConnector needs Unix sockets; on Windows use a local
        # TCP bridge that still relays via `docker system dial-stdio`.
        if sys.platform == "win32":
            connector_kwargs: dict = {}
            if not strict_ssh_host_keys:
                connector_kwargs["known_hosts"] = None
            connector = WindowsSSHDockerConnector(
                docker_url,
                strict_host_keys=strict_ssh_host_keys,
                **connector_kwargs,
            )
            client = aiodocker.Docker(
                url="http://windows-ssh-docker.local",
                connector=connector,
                api_version=settings.docker_api_version,
            )
            # aiodocker leaves caller-supplied connectors unowned; make the
            # session close the TCP/SSH bridge so resources are released.
            client.session._connector_owner = True  # type: ignore[attr-defined]
            return client

        if not strict_ssh_host_keys:
            connector = SSHConnector(docker_url, strict_host_keys=False)
            if connector._ssh_username:
                connector._ssh_username = unquote(connector._ssh_username)
            if connector._ssh_password:
                connector._ssh_password = unquote(connector._ssh_password)
            if not connector._ssh_username:
                raise ValueError("SSH Docker URL must include a username")

            original_clean_environment = connector._clean_environment

            def clean_environment_with_user() -> dict[str, str]:
                env = original_clean_environment()
                # Minimal container images may not define a local username.
                # AsyncSSH asks for one even when a remote username is provided,
                # so use the remote SSH username as a harmless local fallback.
                env.setdefault("USER", connector._ssh_username)
                env.setdefault("LOGNAME", connector._ssh_username)
                return env

            connector._clean_environment = clean_environment_with_user
            # SSHConnector still auto-loads ~/.ssh/known_hosts when that file exists.
            # For user-entered hosts in the WebUI, explicitly disable AsyncSSH host
            # key checking so users do not need to pre-register arbitrary IPs.
            connector._ssh_options["known_hosts"] = None
            return aiodocker.Docker(
                url="unix://localhost",
                connector=connector,
                api_version=settings.docker_api_version,
            )

    return aiodocker.Docker(
        url=docker_url,
        ssl_context=ssl_context,
        api_version=settings.docker_api_version,
    )


async def create_configured_docker_client(
    tenant_id: str | None = None,
) -> aiodocker.Docker:
    """Create a Docker client from DB remote config, falling back to .env."""
    docker_url, from_db = await resolve_docker_url(tenant_id=tenant_id)
    return create_docker_client(
        docker_url=docker_url,
        strict_ssh_host_keys=not from_db,
    )


async def resolve_docker_url(tenant_id: str | None = None) -> tuple[str, bool]:
    """Resolve Docker URL from DB remote SSH config or .env fallback."""
    tenant = tenant_id or settings.default_tenant_id
    try:
        async with async_session_maker() as session:
            row = await session.scalar(
                select(RemoteDockerConfig).where(RemoteDockerConfig.tenant_id == tenant)
            )
    except SQLAlchemyError:
        return settings.resolved_docker_url, False

    if row and row.enabled and row.ssh_host.strip() and row.ssh_username.strip():
        return (
            build_ssh_docker_url(
                username=row.ssh_username,
                password=row.ssh_password,
                host=row.ssh_host,
                port=row.ssh_port,
            ),
            True,
        )
    return settings.resolved_docker_url, False


def mask_docker_url(docker_url: str) -> str:
    """Mask credentials in Docker endpoint URLs before logging or returning errors."""
    parsed = urlsplit(docker_url)
    if not parsed.username and not parsed.password:
        return docker_url

    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:********@{host}{port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _docker_ssl_context() -> ssl.SSLContext | None:
    """Build an SSL context for TLS-protected Docker TCP endpoints."""
    if not settings.docker_tls_verify:
        return None

    cert_path = Path(settings.docker_cert_path).expanduser()
    cafile = cert_path / "ca.pem" if settings.docker_cert_path else None
    certfile = cert_path / "cert.pem" if settings.docker_cert_path else None
    keyfile = cert_path / "key.pem" if settings.docker_cert_path else None

    context = ssl.create_default_context(cafile=str(cafile) if cafile else None)
    if certfile and keyfile:
        context.load_cert_chain(str(certfile), str(keyfile))
    return context

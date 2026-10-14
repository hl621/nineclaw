"""Windows-compatible SSH Docker access via local TCP + dial-stdio.

aiodocker's SSHConnector subclasses UnixConnector and calls
``asyncio.start_unix_server``, which is unavailable on Windows. This module
provides the same ``docker system dial-stdio`` relay over a localhost TCP
server so aiodocker can talk to a remote Docker Engine from Windows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp
from aiodocker.exceptions import DockerError

try:
    import asyncssh
except ImportError:  # pragma: no cover
    asyncssh = None  # type: ignore

log = logging.getLogger(__name__)

DEFAULT_SSH_PORT = 22
DANGEROUS_ENV_VARS = ["LD_LIBRARY_PATH", "SSL_CERT_FILE", "SSL_CERT_DIR", "PYTHONPATH"]


class WindowsSSHDockerConnector(aiohttp.TCPConnector):
    """TCP connector that tunnels Docker HTTP API over SSH dial-stdio."""

    def __init__(
        self,
        ssh_url: str,
        *,
        strict_host_keys: bool = True,
        **kwargs: Any,
    ) -> None:
        if asyncssh is None:
            raise DockerError(
                500,
                "asyncssh is required for SSH connections. "
                "Install with: pip install aiodocker[ssh]",
            )

        parsed = urlparse(ssh_url)
        if parsed.scheme != "ssh":
            raise DockerError(400, f"Invalid SSH URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise DockerError(400, "SSH URL must include hostname")

        self._ssh_host = parsed.hostname
        self._ssh_port = parsed.port or DEFAULT_SSH_PORT
        self._ssh_username = unquote(parsed.username) if parsed.username else None
        self._ssh_password = unquote(parsed.password) if parsed.password else None
        self._strict_host_keys = strict_host_keys
        self._ssh_options: dict[str, Any] = dict(kwargs)

        if not self._ssh_username:
            raise ValueError("SSH Docker URL must include a username")

        if self._ssh_options.get("known_hosts") is None and self._strict_host_keys:
            raise DockerError(
                400,
                "Host key verification is required for security. "
                "Either add the host to ~/.ssh/known_hosts or set strict_host_keys=False.",
            )

        self._ssh_conn: Any | None = None
        self._ssh_context: Any | None = None
        self._tunnel_lock = asyncio.Lock()
        self._socket_server: asyncio.Server | None = None
        self._local_port: int | None = None
        self._relay_tasks: set[asyncio.Task[None]] = set()

        super().__init__()

    def _sanitize_error_message(self, error: Exception) -> str:
        message = str(error)
        if self._ssh_password:
            message = message.replace(self._ssh_password, "***REDACTED***")
        return re.sub(
            r"ssh://([^:/@]+):([^@]+)@",
            r"ssh://\1:***REDACTED***@",
            message,
        )

    def _clean_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        for var in DANGEROUS_ENV_VARS:
            env.pop(var, None)
        env.setdefault("USER", self._ssh_username or "docker")
        env.setdefault("LOGNAME", self._ssh_username or "docker")
        return env

    async def _relay_data(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (asyncio.CancelledError, ConnectionError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_docker_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        process = None
        try:
            if self._ssh_conn is None:
                raise DockerError(500, "SSH connection not established")

            process = await self._ssh_conn.create_process(
                "docker system dial-stdio",
                encoding=None,
            )
            send_task = asyncio.create_task(
                self._relay_data(reader, process.stdin)  # type: ignore[arg-type]
            )
            recv_task = asyncio.create_task(
                self._relay_data(process.stdout, writer)  # type: ignore[arg-type]
            )
            self._relay_tasks.update({send_task, recv_task})

            done, pending = await asyncio.wait(
                [send_task, recv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._relay_tasks.discard(send_task)
            self._relay_tasks.discard(recv_task)
        except Exception as exc:
            log.error("Error in dial-stdio relay: %s", self._sanitize_error_message(exc))
        finally:
            if process is not None:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _ensure_ssh_tunnel(self) -> None:
        async with self._tunnel_lock:
            if self._ssh_conn is not None and not self._ssh_conn.is_closed():
                return

            log.debug(
                "Establishing Windows SSH Docker bridge to %s@%s:%s",
                self._ssh_username,
                self._ssh_host,
                self._ssh_port,
            )
            try:
                self._ssh_context = asyncssh.connect(
                    host=self._ssh_host,
                    port=self._ssh_port,
                    username=self._ssh_username,
                    password=self._ssh_password,
                    env=self._clean_environment(),
                    **self._ssh_options,
                )
                self._ssh_conn = await self._ssh_context.__aenter__()
                self._socket_server = await asyncio.start_server(
                    self._handle_docker_connection,
                    host="127.0.0.1",
                    port=0,
                )
                sockets = self._socket_server.sockets
                if not sockets:
                    raise DockerError(500, "Failed to bind local Docker SSH bridge")
                self._local_port = int(sockets[0].getsockname()[1])
                log.info(
                    "Windows SSH Docker bridge listening on 127.0.0.1:%s",
                    self._local_port,
                )
                # 注意：不要在这里清空 _ssh_password。SSH 隧道可能因空闲
                # 超时/网络抖动断开，_ensure_ssh_tunnel 重连时仍需密码认证；
                # 清空会导致重连必定 Permission denied。
            except Exception as exc:
                sanitized = self._sanitize_error_message(exc)
                log.error("Failed to establish SSH Docker bridge: %s", sanitized)
                await self._cleanup_tunnel()
                raise DockerError(
                    500,
                    f"Cannot connect to Docker via SSH "
                    f"{self._ssh_username}@{self._ssh_host}:{self._ssh_port}: {sanitized}",
                ) from exc

    async def _cleanup_tunnel(self) -> None:
        for task in list(self._relay_tasks):
            task.cancel()
        self._relay_tasks.clear()

        if self._socket_server is not None:
            self._socket_server.close()
            try:
                await self._socket_server.wait_closed()
            except Exception:
                pass
            self._socket_server = None
            self._local_port = None

        if self._ssh_context is not None:
            try:
                await self._ssh_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._ssh_context = None
            self._ssh_conn = None

    async def _resolve_host(
        self,
        host: str,
        port: int,
        traces: list[Any],
    ) -> list[dict[str, Any]]:
        await self._ensure_ssh_tunnel()
        assert self._local_port is not None
        return [
            {
                "hostname": "127.0.0.1",
                "host": "127.0.0.1",
                "port": self._local_port,
                "family": 0,
                "proto": 0,
                "flags": 0,
            }
        ]

    async def close(self) -> None:
        await self._cleanup_tunnel()
        await super().close()

"""Interactive terminal sessions backed by Docker exec PTYs."""

from __future__ import annotations

import asyncio
import codecs
import logging
import time
import uuid
from collections import deque
from codecs import IncrementalDecoder
from dataclasses import dataclass, field
from typing import Any

from aiodocker.containers import DockerContainer
from aiodocker.execs import Exec
from aiodocker.stream import Stream

from app.core.config import settings
from app.services.docker_service import DockerService

logger = logging.getLogger(__name__)

MAX_BUFFER_CHARS = 200_000


class TerminalLimitError(RuntimeError):
    """Raised when an instance already has the maximum number of terminals."""


@dataclass
class TerminalClient:
    queue: asyncio.Queue[dict[str, Any]]


@dataclass
class TerminalSession:
    id: str
    instance_id: str
    container_id: str
    title: str
    exec_obj: Exec
    stream: Stream
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    cols: int = 120
    rows: int = 32
    clients: list[TerminalClient] = field(default_factory=list)
    buffer: deque[str] = field(default_factory=deque)
    buffer_chars: int = 0
    closed: bool = False
    reader_task: asyncio.Task[None] | None = None
    # Hold incomplete UTF-8 sequences across Docker stream chunks.
    utf8_decoder: IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(errors="replace")
    )


class TerminalService:
    """Process-local registry for per-instance terminal sessions."""

    def __init__(self, docker_service: DockerService) -> None:
        self._docker = docker_service
        self._sessions: dict[str, TerminalSession] = {}
        self._by_instance: dict[str, list[str]] = {}
        self._next_index: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start background cleanup for idle detached terminals."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        """Stop cleanup and close all active terminal sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        async with self._lock:
            sessions = list(self._sessions.values())
        await asyncio.gather(
            *(self._close_session(session, reason="manager shutdown") for session in sessions),
            return_exceptions=True,
        )

    async def list_terminals(self, instance_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            ids = list(self._by_instance.get(instance_id, []))
            return [
                self._serialize(self._sessions[terminal_id])
                for terminal_id in ids
                if terminal_id in self._sessions and not self._sessions[terminal_id].closed
            ]

    async def create_terminal(
        self,
        *,
        instance_id: str,
        container_id: str,
        cols: int = 120,
        rows: int = 32,
    ) -> dict[str, Any]:
        terminal_id = uuid.uuid4().hex[:16]
        async with self._lock:
            live_ids = [
                terminal_id
                for terminal_id in self._by_instance.get(instance_id, [])
                if terminal_id in self._sessions and not self._sessions[terminal_id].closed
            ]
            if len(live_ids) >= settings.terminal_max_sessions_per_instance:
                raise TerminalLimitError(
                    f"Instance {instance_id} already has {len(live_ids)} active terminals"
                )
            index = self._next_index.get(instance_id, 0) + 1
            self._next_index[instance_id] = index
        title = f"terminal-{index}"

        container = DockerContainer(self._docker.client, id=container_id)
        exec_obj = await container.exec(
            [
                "/bin/sh",
                "-c",
                "cd /workspace 2>/dev/null || cd /; "
                # Non-login interactive bash: inherits the image ENV PATH
                # (e.g. /opt/hermes/.venv/bin for `hermes`) and reads
                # ~/.bashrc. A login shell (`bash -l`) sources /etc/profile,
                # which hard-resets PATH and drops those entries — matching
                # `docker exec -it <c> bash` behavior instead.
                "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi",
            ],
            stdout=True,
            stderr=True,
            stdin=True,
            tty=True,
            environment={
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                # Force UTF-8 so Chinese / emoji render correctly in WebUI xterm.
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "LC_CTYPE": "C.UTF-8",
            },
        )
        stream = exec_obj.start()
        session = TerminalSession(
            id=terminal_id,
            instance_id=instance_id,
            container_id=container_id,
            title=title,
            exec_obj=exec_obj,
            stream=stream,
            cols=cols,
            rows=rows,
        )

        async with self._lock:
            self._sessions[terminal_id] = session
            self._by_instance.setdefault(instance_id, []).append(terminal_id)
        session.reader_task = asyncio.create_task(self._read_loop(session))
        asyncio.create_task(self._delayed_resize(session, cols=cols, rows=rows))

        logger.info("Created terminal %s for instance %s", terminal_id, instance_id)
        return self._serialize(session)

    async def attach(self, instance_id: str, terminal_id: str) -> TerminalClient:
        session = self._get_session(instance_id, terminal_id)
        client = TerminalClient(queue=asyncio.Queue(maxsize=500))
        session.clients.append(client)
        session.last_active_at = time.time()
        if session.buffer:
            await client.queue.put({"type": "output", "data": "".join(session.buffer)})
        await client.queue.put({"type": "ready", "terminal": self._serialize(session)})
        return client

    async def detach(self, instance_id: str, terminal_id: str, client: TerminalClient) -> None:
        try:
            session = self._get_session(instance_id, terminal_id)
        except KeyError:
            return
        if client in session.clients:
            session.clients.remove(client)
        session.last_active_at = time.time()

    async def write(self, instance_id: str, terminal_id: str, data: str) -> None:
        session = self._get_session(instance_id, terminal_id)
        if session.closed:
            return
        session.last_active_at = time.time()
        await session.stream.write_in(data.encode("utf-8"))

    async def resize(self, instance_id: str, terminal_id: str, cols: int, rows: int) -> None:
        session = self._get_session(instance_id, terminal_id)
        session.cols = max(1, cols)
        session.rows = max(1, rows)
        session.last_active_at = time.time()
        await self._resize_best_effort(session, cols=session.cols, rows=session.rows)

    async def close_terminal(self, instance_id: str, terminal_id: str) -> None:
        session = self._get_session(instance_id, terminal_id)
        await self._close_session(session, reason="closed by user")

    async def close_instance(self, instance_id: str, reason: str = "instance lifecycle changed") -> None:
        for item in await self.list_terminals(instance_id):
            try:
                session = self._get_session(instance_id, item["id"])
            except KeyError:
                continue
            await self._close_session(session, reason=reason)

    def _get_session(self, instance_id: str, terminal_id: str) -> TerminalSession:
        session = self._sessions.get(terminal_id)
        if session is None or session.instance_id != instance_id or session.closed:
            raise KeyError(terminal_id)
        return session

    async def _delayed_resize(self, session: TerminalSession, *, cols: int, rows: int) -> None:
        await asyncio.sleep(0.25)
        if not session.closed:
            await self._resize_best_effort(session, cols=cols, rows=rows)

    async def _resize_best_effort(self, session: TerminalSession, *, cols: int, rows: int) -> None:
        try:
            await asyncio.wait_for(
                session.exec_obj.resize(h=max(1, rows), w=max(1, cols)),
                timeout=settings.terminal_resize_timeout_seconds,
            )
        except Exception:
            logger.debug("Terminal resize skipped for %s", session.id, exc_info=True)

    async def _read_loop(self, session: TerminalSession) -> None:
        try:
            while not session.closed:
                msg = await session.stream.read_out()
                if msg is None:
                    break
                # Incremental decode: Docker may split a UTF-8 codepoint across chunks.
                # Per-chunk decode(..., errors="replace") caused Chinese/emoji mojibake.
                chunk = msg.data if isinstance(msg.data, (bytes, bytearray)) else bytes(msg.data)
                text = session.utf8_decoder.decode(chunk, final=False)
                if not text:
                    continue
                session.last_active_at = time.time()
                self._append_buffer(session, text)
                await self._broadcast(session, {"type": "output", "data": text})
        except Exception:
            if not session.closed:
                logger.exception("Terminal read loop failed: %s", session.id)
                await self._broadcast(
                    session,
                    {"type": "error", "message": "terminal stream closed unexpectedly"},
                )
        finally:
            try:
                trailing = session.utf8_decoder.decode(b"", final=True)
            except Exception:
                trailing = ""
            if trailing and not session.closed:
                self._append_buffer(session, trailing)
                await self._broadcast(session, {"type": "output", "data": trailing})
            await self._mark_closed(session, reason="process exited")

    def _append_buffer(self, session: TerminalSession, text: str) -> None:
        session.buffer.append(text)
        session.buffer_chars += len(text)
        while session.buffer_chars > MAX_BUFFER_CHARS and session.buffer:
            session.buffer_chars -= len(session.buffer.popleft())

    async def _broadcast(self, session: TerminalSession, payload: dict[str, Any]) -> None:
        stale: list[TerminalClient] = []
        for client in list(session.clients):
            try:
                client.queue.put_nowait(payload)
            except asyncio.QueueFull:
                stale.append(client)
        for client in stale:
            if client in session.clients:
                session.clients.remove(client)

    async def _close_session(self, session: TerminalSession, reason: str) -> None:
        if session.closed:
            return
        session.closed = True
        try:
            await session.stream.write_in(b"exit\n")
        except Exception:
            pass
        try:
            await session.stream.close()
        except Exception:
            pass
        if session.reader_task:
            session.reader_task.cancel()
        await self._mark_closed(session, reason=reason)

    async def _mark_closed(self, session: TerminalSession, reason: str) -> None:
        if not session.closed:
            session.closed = True
        await self._broadcast(
            session,
            {"type": "closed", "terminal_id": session.id, "reason": reason},
        )
        async with self._lock:
            self._sessions.pop(session.id, None)
            ids = self._by_instance.get(session.instance_id)
            if ids:
                self._by_instance[session.instance_id] = [tid for tid in ids if tid != session.id]
                if not self._by_instance[session.instance_id]:
                    self._by_instance.pop(session.instance_id, None)

    async def _cleanup_loop(self) -> None:
        interval = max(5, settings.terminal_cleanup_interval_seconds)
        idle_timeout = max(60, settings.terminal_idle_timeout_seconds)
        while True:
            await asyncio.sleep(interval)
            now = time.time()
            async with self._lock:
                idle_sessions = [
                    session
                    for session in self._sessions.values()
                    if not session.closed
                    and not session.clients
                    and now - session.last_active_at >= idle_timeout
                ]
            for session in idle_sessions:
                logger.info(
                    "Closing idle terminal %s for instance %s after %.0fs",
                    session.id,
                    session.instance_id,
                    now - session.last_active_at,
                )
                await self._close_session(session, reason="idle timeout")

    @staticmethod
    def _serialize(session: TerminalSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "title": session.title,
            "instance_id": session.instance_id,
            "created_at": session.created_at,
            "last_active_at": session.last_active_at,
            "cols": session.cols,
            "rows": session.rows,
            "connected_clients": len(session.clients),
            "idle_seconds": max(0, int(time.time() - session.last_active_at)),
        }

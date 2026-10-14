"""SSE file change watcher for Skill Studio."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

POLL_INTERVAL_S = 1.0
DEBOUNCE_S = 0.2
KEEPALIVE_S = 15.0
IDLE_STOP_DELAY_S = 15.0
MAX_QUEUE_SIZE = 200


@dataclass(frozen=True)
class FileState:
    kind: str
    size: int
    mtime_ns: int


@dataclass
class WatchEntry:
    key: str
    root: Path
    subscribers: set[asyncio.Queue[str]] = field(default_factory=set)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    idle_task: asyncio.Task | None = None


_watchers: dict[str, WatchEntry] = {}
_watchers_lock = asyncio.Lock()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _safe_rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan(root: Path) -> dict[str, FileState]:
    snapshot: dict[str, FileState] = {}
    if not root.exists():
        return snapshot

    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if path.is_dir():
            kind = "folder"
            size = 0
        elif path.is_file():
            kind = "file"
            size = stat.st_size
        else:
            continue
        snapshot[_safe_rel(root, path)] = FileState(
            kind=kind,
            size=size,
            mtime_ns=stat.st_mtime_ns,
        )
    return snapshot


def _diff_events(
    old: dict[str, FileState],
    new: dict[str, FileState],
    slug: str,
) -> list[dict]:
    events: list[dict] = []
    tree_changed = False
    now = int(time.time() * 1000)

    for path in sorted(new.keys() - old.keys()):
        state = new[path]
        tree_changed = True
        events.append({
            "type": f"{state.kind}.created",
            "slug": slug,
            "path": path,
            "kind": state.kind,
            "size": state.size,
            "mtime_ns": state.mtime_ns,
            "ts": now,
        })

    for path in sorted(old.keys() - new.keys()):
        state = old[path]
        tree_changed = True
        events.append({
            "type": f"{state.kind}.deleted",
            "slug": slug,
            "path": path,
            "kind": state.kind,
            "ts": now,
        })

    for path in sorted(old.keys() & new.keys()):
        before = old[path]
        after = new[path]
        if before.kind != after.kind:
            tree_changed = True
            events.append({
                "type": f"{after.kind}.modified",
                "slug": slug,
                "path": path,
                "kind": after.kind,
                "size": after.size,
                "mtime_ns": after.mtime_ns,
                "ts": now,
            })
        elif after.kind == "file" and (
            before.size != after.size or before.mtime_ns != after.mtime_ns
        ):
            events.append({
                "type": "file.modified",
                "slug": slug,
                "path": path,
                "kind": "file",
                "size": after.size,
                "mtime_ns": after.mtime_ns,
                "ts": now,
            })

    if tree_changed:
        events.append({"type": "tree.changed", "slug": slug, "ts": now})
    return events


async def _broadcast(entry: WatchEntry, event: dict) -> None:
    payload = _sse("file", event)
    for queue in list(entry.subscribers):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def _watch_loop(entry: WatchEntry, slug: str) -> None:
    previous = _scan(entry.root)
    try:
        while not entry.stop_event.is_set():
            try:
                await asyncio.wait_for(entry.stop_event.wait(), timeout=POLL_INTERVAL_S)
                break
            except asyncio.TimeoutError:
                pass

            current = _scan(entry.root)
            events = _diff_events(previous, current, slug)
            if events:
                await asyncio.sleep(DEBOUNCE_S)
                current = _scan(entry.root)
                events = _diff_events(previous, current, slug)
                previous = current
                for event in events:
                    await _broadcast(entry, event)
            else:
                previous = current
    finally:
        entry.stop_event.set()


async def _stop_when_idle(key: str, delay_s: float = IDLE_STOP_DELAY_S) -> None:
    await asyncio.sleep(delay_s)
    async with _watchers_lock:
        entry = _watchers.get(key)
        if not entry or entry.subscribers:
            return
        entry.stop_event.set()
        if entry.task:
            entry.task.cancel()
        _watchers.pop(key, None)


async def watch_skill_files(
    tenant_id: str,
    slug: str,
    root: Path,
) -> AsyncGenerator[str, None]:
    key = f"{tenant_id}:{slug}:{root}"
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

    async with _watchers_lock:
        entry = _watchers.get(key)
        if not entry:
            entry = WatchEntry(key=key, root=root)
            entry.task = asyncio.create_task(_watch_loop(entry, slug))
            _watchers[key] = entry
        if entry.idle_task and not entry.idle_task.done():
            entry.idle_task.cancel()
            entry.idle_task = None
        entry.subscribers.add(queue)

    try:
        yield _sse("file", {"type": "watch.connected", "slug": slug})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                yield event
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        async with _watchers_lock:
            entry = _watchers.get(key)
            if not entry:
                return
            entry.subscribers.discard(queue)
            if not entry.subscribers:
                entry.idle_task = asyncio.create_task(_stop_when_idle(key))

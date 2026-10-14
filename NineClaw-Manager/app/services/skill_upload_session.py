"""On-disk upload session store for the multi-skill import flow.

The skill upload modal is split into two HTTP calls:

1. ``POST /v1/skills/preview``  – server parses the zip, returns a
   ``session_id`` and the list of detected skills.
2. ``POST /v1/skills/import``   – the client refers to the session_id
   and the server streams a per-skill SSE progress feed.

We keep the cached zip + detection result in
``<settings.skills_storage_path>/.upload-sessions/<session_id>/`` so
that:

* Multi-worker uvicorn deployments work — every worker shares the
  same filesystem and any worker can satisfy the import call no
  matter which worker handled the preview.
* Sessions survive a single-process restart; the operator just
  cleans the directory on a full redeploy if they care.
* Cleanup is straightforward: lazy TTL eviction on every access.

Each session directory contains:

* ``bundle.zip`` – the original upload bytes.
* ``meta.json``  – ``{filename, detected, created_at}``.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UploadSession:
    """A pending multi-skill upload waiting to be imported."""

    session_id: str
    filename: str
    detected: list[dict[str, Any]]
    zip_bytes: bytes


class UploadSessionStore:
    """Disk-backed store with a configurable TTL.

    The directory is created lazily on first use; each session lives
    in its own subdirectory keyed by an opaque token.
    """

    BUNDLE_NAME = "bundle.zip"
    META_NAME = "meta.json"

    def __init__(self, root_dir: Path | str, ttl_seconds: float = 1800.0) -> None:
        self.root = Path(root_dir).expanduser().resolve()
        self.ttl = ttl_seconds

    # ── Public API ────────────────────────────────────────────────────

    def create(
        self,
        *,
        zip_bytes: bytes,
        filename: str,
        detected: list[dict[str, Any]],
    ) -> UploadSession:
        self._ensure_root()
        self._evict_expired()
        session_id = secrets.token_urlsafe(18)
        session_dir = self.root / session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        bundle_path = session_dir / self.BUNDLE_NAME
        meta_path = session_dir / self.META_NAME
        bundle_path.write_bytes(zip_bytes)
        meta_path.write_text(
            json.dumps(
                {
                    "filename": filename,
                    "detected": detected,
                    "created_at": time.time(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return UploadSession(
            session_id=session_id,
            filename=filename,
            detected=detected,
            zip_bytes=zip_bytes,
        )

    def get(self, session_id: str) -> UploadSession | None:
        if not _is_safe_session_id(session_id):
            return None
        self._evict_expired()
        session_dir = self.root / session_id
        bundle_path = session_dir / self.BUNDLE_NAME
        meta_path = session_dir / self.META_NAME
        if not bundle_path.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - float(meta.get("created_at", 0)) > self.ttl:
            self.delete(session_id)
            return None
        try:
            zip_bytes = bundle_path.read_bytes()
        except OSError:
            return None
        return UploadSession(
            session_id=session_id,
            filename=str(meta.get("filename") or ""),
            detected=list(meta.get("detected") or []),
            zip_bytes=zip_bytes,
        )

    def delete(self, session_id: str) -> bool:
        if not _is_safe_session_id(session_id):
            return False
        session_dir = self.root / session_id
        if not session_dir.is_dir():
            return False
        shutil.rmtree(session_dir, ignore_errors=True)
        return True

    # ── Internals ─────────────────────────────────────────────────────

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _evict_expired(self) -> None:
        if not self.root.is_dir():
            return
        cutoff = time.time() - self.ttl
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            meta_path = entry / self.META_NAME
            try:
                created = (
                    float(
                        json.loads(meta_path.read_text(encoding="utf-8")).get(
                            "created_at", 0
                        )
                    )
                    if meta_path.is_file()
                    else entry.stat().st_mtime
                )
            except (OSError, ValueError):
                # Corrupt session directory — drop it.
                shutil.rmtree(entry, ignore_errors=True)
                continue
            if created < cutoff:
                shutil.rmtree(entry, ignore_errors=True)


def _is_safe_session_id(value: str) -> bool:
    """Defensive guard against path-traversal via the session_id route param."""
    if not value or len(value) > 128:
        return False
    # ``token_urlsafe`` outputs URL-safe base64: A-Z, a-z, 0-9, -, _.
    return all(ch.isalnum() or ch in "-_" for ch in value)


# Module-level singleton — the FastAPI dependency below returns this
# instance so all requests share one store.
_store_singleton: UploadSessionStore | None = None


def get_upload_session_store() -> UploadSessionStore:
    """Lazy singleton; reads ``settings.skills_storage_path`` on first call."""
    global _store_singleton
    if _store_singleton is None:
        # Import inside the function so test code that overrides
        # SKILLS_STORAGE_PATH and reloads `app.core.config` picks up
        # the new value here too.
        from app.core.config import settings

        _store_singleton = UploadSessionStore(
            root_dir=Path(settings.skills_storage_path).expanduser() / ".upload-sessions",
        )
    return _store_singleton


def reset_session_store_singleton_for_tests() -> None:
    """Drop the cached store so a test can swap storage roots."""
    global _store_singleton
    _store_singleton = None

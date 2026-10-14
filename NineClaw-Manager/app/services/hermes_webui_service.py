"""Hermes WebUI HTTP client — session list and conversation-round stats.

Proxies the Hermes WebUI REST API (container port 8643) for a specific
nineclaw instance via Traefik:

  {resolved Traefik URL}/traefik/nineclaw/{instance_id}/webui/api/...

No authentication is required for the webui service.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.services.nineclaw_bootstrap import build_webui_api_base_url

logger = logging.getLogger(__name__)

_CONVERSATION_ROUNDS_BATCH = 8
_INSTANCE_STATS_CONCURRENCY = 4

_client_pool: dict[str, httpx.AsyncClient] = {}


class WebUIError(Exception):
    """Raised when the Hermes WebUI returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"WebUI error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _get_pooled_client(base_url: str) -> httpx.AsyncClient:
    key = base_url.rstrip("/")
    if key not in _client_pool:
        _client_pool[key] = httpx.AsyncClient(
            base_url=key + "/",
            timeout=30.0,
        )
    return _client_pool[key]


class HermesWebUIService:
    """Async HTTP client for the Hermes WebUI REST API."""

    def __init__(self, instance_id: str) -> None:
        self._instance_id = instance_id
        self._base_url = build_webui_api_base_url(instance_id)
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = _get_pooled_client(self._base_url)

    async def close(self) -> None:
        self._client = None

    async def __aenter__(self) -> "HermesWebUIService":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HermesWebUIService not connected — call connect() first")
        return self._client

    def _raise_or_json(self, resp: httpx.Response) -> Any:
        if resp.is_success:
            if not resp.content:
                return {}
            return resp.json()
        detail = resp.text
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                detail = str(payload.get("error") or payload.get("message") or detail)
        except Exception:
            pass
        raise WebUIError(resp.status_code, detail)

    async def list_sessions(self) -> list[dict[str, Any]]:
        data = self._raise_or_json(await self._http.get("sessions"))
        sessions = data.get("sessions") if isinstance(data, dict) else None
        return sessions if isinstance(sessions, list) else []

    async def get_session_conversation_rounds(self, session_id: str) -> int:
        data = self._raise_or_json(
            await self._http.post(
                "session/conversation-rounds",
                json={"session_id": session_id},
            )
        )
        rounds = data.get("rounds") if isinstance(data, dict) else None
        if isinstance(rounds, (int, float)) and rounds >= 0:
            return int(rounds)
        return 0

    async def get_total_conversation_rounds(self) -> int:
        sessions = await self.list_sessions()
        session_ids = [
            str(item.get("session_id"))
            for item in sessions
            if isinstance(item, dict)
            and item.get("session_id")
            and (item.get("message_count") or 0) > 0
        ]
        if not session_ids:
            return 0

        total = 0
        for offset in range(0, len(session_ids), _CONVERSATION_ROUNDS_BATCH):
            chunk = session_ids[offset : offset + _CONVERSATION_ROUNDS_BATCH]
            results = await asyncio.gather(
                *(self._safe_session_rounds(sid) for sid in chunk),
                return_exceptions=True,
            )
            for value in results:
                if isinstance(value, int):
                    total += value
        return total

    async def _safe_session_rounds(self, session_id: str) -> int:
        try:
            return await self.get_session_conversation_rounds(session_id)
        except Exception as exc:
            logger.debug(
                "conversation-rounds failed for instance=%s session=%s: %s",
                self._instance_id,
                session_id,
                exc,
            )
            return 0


async def fetch_instance_conversation_rounds(instance_id: str) -> int:
    """Return total conversation rounds for one instance, or 0 on failure."""
    try:
        async with HermesWebUIService(instance_id) as svc:
            return await svc.get_total_conversation_rounds()
    except Exception as exc:
        logger.debug("instance conversation-rounds stats failed for %s: %s", instance_id, exc)
        return 0


async def fetch_instances_conversation_rounds(instance_ids: list[str]) -> dict[str, int]:
    """Return conversation-round totals keyed by instance id."""
    unique_ids = [instance_id for instance_id in dict.fromkeys(instance_ids) if instance_id]
    if not unique_ids:
        return {}

    semaphore = asyncio.Semaphore(_INSTANCE_STATS_CONCURRENCY)

    async def _fetch_one(instance_id: str) -> tuple[str, int]:
        async with semaphore:
            rounds = await fetch_instance_conversation_rounds(instance_id)
            return instance_id, rounds

    pairs = await asyncio.gather(*(_fetch_one(instance_id) for instance_id in unique_ids))
    return dict(pairs)

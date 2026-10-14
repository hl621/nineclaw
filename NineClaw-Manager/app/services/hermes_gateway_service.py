"""Hermes Gateway HTTP Client — OpenAI-compatible REST API client.

The Hermes gateway (container port 8642) exposes an OpenAI-compatible
HTTP API server (aiohttp). This client wraps that REST API.

Routing through Traefik:
  {resolved Traefik URL}/traefik/nineclaw/{instance_id}/gateway/...

Traefik strips the /traefik/nineclaw/{instance_id}/gateway/ prefix and
forwards to the container's port 8642.

Authentication: Bearer token via Authorization header.
  Authorization: Bearer {hermes_gateway_token}

API surface (from gateway/platforms/api_server.py):

  Health
    GET  /health
    GET  /health/detailed
    GET  /v1/health

  Models
    GET  /v1/models
    GET  /v1/capabilities

  Chat Completions (OpenAI-compatible)
    POST /v1/chat/completions

  Responses API (stateful, OpenAI Responses format)
    POST   /v1/responses
    GET    /v1/responses/{response_id}
    DELETE /v1/responses/{response_id}

  Runs (async agent execution with SSE events)
    POST /v1/runs
    GET  /v1/runs/{run_id}
    GET  /v1/runs/{run_id}/events   (SSE stream)
    POST /v1/runs/{run_id}/approval
    POST /v1/runs/{run_id}/stop

  Cron Jobs
    GET    /api/jobs
    POST   /api/jobs
    GET    /api/jobs/{job_id}
    PATCH  /api/jobs/{job_id}
    DELETE /api/jobs/{job_id}
    POST   /api/jobs/{job_id}/pause
    POST   /api/jobs/{job_id}/resume
    POST   /api/jobs/{job_id}/run
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_AUTH_HEADER = "Authorization"


class GatewayError(Exception):
    """Raised when the gateway returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Gateway error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class HermesGatewayService:
    """Async HTTP client for the Hermes Gateway OpenAI-compatible REST API.

    One instance per request — call connect() before use and close() when done,
    or use as an async context manager.
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the underlying HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url + "/",
            headers={_AUTH_HEADER: f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "HermesGatewayService":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ─── Internal helpers ─────────────────────────────────────────────────

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "HermesGatewayService not connected — call connect() first"
            )
        return self._client

    async def _get(self, path: str, **params: Any) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None}
        resp = await self._http.get(path.lstrip("/"), params=filtered)
        return self._raise_or_json(resp)

    async def _post(self, path: str, json: Any = None) -> Any:
        resp = await self._http.post(path.lstrip("/"), json=json)
        return self._raise_or_json(resp)

    async def _patch(self, path: str, json: Any) -> Any:
        resp = await self._http.patch(path.lstrip("/"), json=json)
        return self._raise_or_json(resp)

    async def _delete(self, path: str) -> Any:
        resp = await self._http.delete(path.lstrip("/"))
        return self._raise_or_json(resp)

    @staticmethod
    def _raise_or_json(resp: httpx.Response) -> Any:
        if resp.is_error:
            try:
                detail = resp.json().get("error", {}).get("message") or resp.text
            except Exception:
                detail = resp.text or resp.reason_phrase
            raise GatewayError(status_code=resp.status_code, detail=str(detail))
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ─── Health ───────────────────────────────────────────────────────────

    async def health(self) -> Any:
        """GET /health — basic health check."""
        return await self._get("health")

    async def health_detailed(self) -> Any:
        """GET /health/detailed — rich status for cross-container probing."""
        return await self._get("health/detailed")

    # ─── Runtime control ──────────────────────────────────────────────────

    async def reload_mcp(self) -> Any:
        """POST /api/mcp/reload — reconnect MCP without restarting the gateway."""
        return await self._post("api/mcp/reload")

    # ─── Models / Capabilities ────────────────────────────────────────────

    async def list_models(self) -> Any:
        """GET /v1/models — list available models (OpenAI format)."""
        return await self._get("v1/models")

    async def get_capabilities(self) -> Any:
        """GET /v1/capabilities — machine-readable API capabilities."""
        return await self._get("v1/capabilities")

    # ─── Chat Completions ─────────────────────────────────────────────────

    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = "hermes-agent",
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """POST /v1/chat/completions — OpenAI-compatible chat completions.

        For streaming responses (stream=True), returns the raw httpx response.
        Callers are responsible for reading the SSE stream.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }
        if stream:
            # Return raw response for SSE streaming — caller reads it
            resp = await self._http.post("v1/chat/completions", json=body)
            if resp.is_error:
                raise GatewayError(status_code=resp.status_code, detail=resp.text)
            return resp
        return await self._post("v1/chat/completions", json=body)

    # ─── Responses API ────────────────────────────────────────────────────

    async def create_response(
        self,
        input: str | list[dict[str, Any]],
        model: str = "hermes-agent",
        previous_response_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """POST /v1/responses — stateful OpenAI Responses API."""
        body: dict[str, Any] = {"model": model, "input": input, **kwargs}
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        return await self._post("v1/responses", json=body)

    async def get_response(self, response_id: str) -> Any:
        """GET /v1/responses/{response_id} — retrieve a stored response."""
        return await self._get(f"v1/responses/{response_id}")

    async def delete_response(self, response_id: str) -> Any:
        """DELETE /v1/responses/{response_id} — delete a stored response."""
        return await self._delete(f"v1/responses/{response_id}")

    # ─── Runs ─────────────────────────────────────────────────────────────

    async def create_run(
        self,
        messages: list[dict[str, Any]],
        model: str = "hermes-agent",
        instructions: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """POST /v1/runs — start an async agent run, returns run_id immediately (202)."""
        # Hermes' asynchronous Runs endpoint uses the Responses-style `input`
        # field, not the Chat Completions `messages` field.
        body: dict[str, Any] = {"model": model, "input": messages, **kwargs}
        if instructions is not None:
            body["instructions"] = instructions
        if session_id is not None:
            body["session_id"] = session_id
        return await self._post("v1/runs", json=body)

    async def get_run(self, run_id: str) -> Any:
        """GET /v1/runs/{run_id} — get current run status."""
        return await self._get(f"v1/runs/{run_id}")

    async def stream_run_events(self, run_id: str) -> httpx.Response:
        """GET /v1/runs/{run_id}/events — SSE stream of structured lifecycle events.

        Returns the raw httpx.Response with streaming enabled.
        The caller is responsible for iterating the response body and closing it.
        Use as an async context manager or call aclose() when done.
        """
        req = self._http.build_request("GET", f"v1/runs/{run_id}/events")
        return await self._http.send(req, stream=True)

    async def approve_run(
        self, run_id: str, decision: str, reason: str | None = None
    ) -> Any:
        """POST /v1/runs/{run_id}/approval — resolve a pending approval.

        decision: "allow" | "deny"
        """
        body: dict[str, Any] = {"decision": decision}
        if reason:
            body["reason"] = reason
        return await self._post(f"v1/runs/{run_id}/approval", json=body)

    async def stop_run(self, run_id: str) -> Any:
        """POST /v1/runs/{run_id}/stop — interrupt a running agent."""
        return await self._post(f"v1/runs/{run_id}/stop")

    # ─── Cron Jobs ────────────────────────────────────────────────────────

    async def list_jobs(self) -> Any:
        """GET /api/jobs — list all cron jobs."""
        return await self._get("api/jobs")

    async def create_job(
        self,
        prompt: str,
        schedule: str,
        name: str | None = None,
        deliver: str = "local",
    ) -> Any:
        """POST /api/jobs — create a new cron job."""
        body: dict[str, Any] = {
            "prompt": prompt,
            "schedule": schedule,
            "deliver": deliver,
        }
        if name:
            body["name"] = name
        return await self._post("api/jobs", json=body)

    async def get_job(self, job_id: str) -> Any:
        """GET /api/jobs/{job_id} — get a single cron job."""
        return await self._get(f"api/jobs/{job_id}")

    async def update_job(self, job_id: str, updates: dict[str, Any]) -> Any:
        """PATCH /api/jobs/{job_id} — update cron job fields."""
        return await self._patch(f"api/jobs/{job_id}", json=updates)

    async def delete_job(self, job_id: str) -> Any:
        """DELETE /api/jobs/{job_id} — delete a cron job."""
        return await self._delete(f"api/jobs/{job_id}")

    async def pause_job(self, job_id: str) -> Any:
        """POST /api/jobs/{job_id}/pause — pause a cron job."""
        return await self._post(f"api/jobs/{job_id}/pause")

    async def resume_job(self, job_id: str) -> Any:
        """POST /api/jobs/{job_id}/resume — resume a paused cron job."""
        return await self._post(f"api/jobs/{job_id}/resume")

    async def run_job(self, job_id: str) -> Any:
        """POST /api/jobs/{job_id}/run — immediately trigger a cron job."""
        return await self._post(f"api/jobs/{job_id}/run")

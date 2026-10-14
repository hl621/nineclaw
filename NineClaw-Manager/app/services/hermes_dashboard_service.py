"""Hermes Dashboard HTTP Client — thin async wrapper around the Hermes REST API.

Proxies every Hermes Dashboard endpoint (port 8644) for a specific nineclaw
instance. All requests are routed through Traefik:

  {resolved Traefik URL}/traefik/nineclaw/{instance_id}/dashboard/api/...

Traefik strips the /traefik/nineclaw/{instance_id}/dashboard/ prefix before
forwarding to the container's port 8644.

Authentication: every request carries the ``X-Hermes-Session-Token`` header
(set from ``settings.hermes_dashboard_token``).

Usage::

    svc = HermesService(base_url="http://traefik/traefik/nineclaw/abc123/dashboard",
                        api_key="sk-...")
    await svc.connect()
    status = await svc.get_status()
    await svc.close()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_SESSION_HEADER = "X-Hermes-Session-Token"

# ─── Connection pool ──────────────────────────────────────────────────────────
# Reuse AsyncClient instances across requests keyed by (base_url, api_key).
# httpx.AsyncClient maintains a connection pool internally, so reusing the
# same client avoids a new TCP handshake on every API call.
# Clients are never explicitly evicted — the pool is small (one per nineclaw
# instance) and long-lived, which is the intended usage pattern.
_client_pool: dict[tuple[str, str], httpx.AsyncClient] = {}


def _get_pooled_client(base_url: str, api_key: str) -> httpx.AsyncClient:
    """Return a cached AsyncClient for the given base_url + api_key pair.

    ``trust_env=False``: Hermes endpoints are reached through the internal
    Traefik URL and must never go through ambient HTTP(S) proxies. Pooled
    clients are long-lived, so a proxy that was merely *temporarily* enabled
    (e.g. a Clash system-proxy toggle) at pool-creation time would otherwise
    be cached forever and hang every later call with ReadTimeout.
    """
    key = (base_url, api_key)
    if key not in _client_pool:
        _client_pool[key] = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={_SESSION_HEADER: api_key},
            timeout=30.0,
            trust_env=False,
        )
    return _client_pool[key]


class HermesError(Exception):
    """Raised when the Hermes dashboard returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Hermes error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class HermesService:
    """Async HTTP client for the Hermes Dashboard REST API.

    One instance per request — call ``connect()`` before use and ``close()``
    when done (or use as an async context manager).
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        # base_url already includes the Traefik prefix up to /dashboard
        # e.g. http://traefik/traefik/nineclaw/abc123/dashboard
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    # ─── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Attach to the pooled HTTP client for this base_url + api_key."""
        self._client = _get_pooled_client(self._base_url, self._api_key)

    async def close(self) -> None:
        """Release the client reference (the pooled client stays open)."""
        self._client = None

    async def __aenter__(self) -> "HermesService":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ─── Internal helpers ─────────────────────────────────────────────────

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HermesService not connected — call connect() first")
        return self._client

    async def _get(self, path: str, **params: Any) -> Any:
        """GET api/{path} and return parsed JSON."""
        filtered = {k: v for k, v in params.items() if v is not None}
        resp = await self._http.get(f"api/{path.lstrip('/')}", params=filtered)
        return self._raise_or_json(resp)

    async def _post(self, path: str, json: Any = None) -> Any:
        """POST api/{path} with optional JSON body."""
        resp = await self._http.post(f"api/{path.lstrip('/')}", json=json)
        return self._raise_or_json(resp)

    async def _put(self, path: str, json: Any) -> Any:
        """PUT api/{path} with JSON body."""
        resp = await self._http.put(f"api/{path.lstrip('/')}", json=json)
        return self._raise_or_json(resp)

    async def _delete(self, path: str, json: Any = None) -> Any:
        """DELETE api/{path} with optional JSON body."""
        resp = await self._http.request(
            "DELETE",
            f"api/{path.lstrip('/')}",
            json=json,
        )
        return self._raise_or_json(resp)

    async def _patch(self, path: str, json: Any) -> Any:
        """PATCH api/{path} with JSON body."""
        resp = await self._http.patch(f"api/{path.lstrip('/')}", json=json)
        return self._raise_or_json(resp)

    @staticmethod
    def _raise_or_json(resp: httpx.Response) -> Any:
        """Raise HermesError on non-2xx, otherwise return parsed JSON."""
        if resp.is_error:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text or resp.reason_phrase
            raise HermesError(status_code=resp.status_code, detail=str(detail))
        # 204 No Content
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ─── Status ───────────────────────────────────────────────────────────

    async def get_status(self) -> Any:
        """GET /api/status — agent version, gateway status, platform states."""
        return await self._get("status")

    # ─── Sessions ─────────────────────────────────────────────────────────

    async def get_sessions(self, limit: int = 20, offset: int = 0) -> Any:
        """GET /api/sessions — paginated session list."""
        return await self._get("sessions", limit=limit, offset=offset)

    async def search_sessions(self, q: str, limit: int = 20) -> Any:
        """GET /api/sessions/search?q=... — full-text search."""
        return await self._get("sessions/search", q=q, limit=limit)

    async def get_session(self, session_id: str) -> Any:
        """GET /api/sessions/{session_id} — single session metadata."""
        return await self._get(f"sessions/{session_id}")

    async def get_session_latest_descendant(self, session_id: str) -> Any:
        """GET /api/sessions/{session_id}/latest-descendant."""
        return await self._get(f"sessions/{session_id}/latest-descendant")

    async def get_session_messages(self, session_id: str) -> Any:
        """GET /api/sessions/{session_id}/messages — full message history."""
        return await self._get(f"sessions/{session_id}/messages")

    async def delete_session(self, session_id: str) -> None:
        """DELETE /api/sessions/{session_id}."""
        await self._delete(f"sessions/{session_id}")

    # ─── Config ───────────────────────────────────────────────────────────

    async def get_config(self) -> Any:
        """GET /api/config — current config.yaml as JSON."""
        return await self._get("config")

    async def get_config_defaults(self) -> Any:
        """GET /api/config/defaults — default configuration values."""
        return await self._get("config/defaults")

    async def get_config_schema(self) -> Any:
        """GET /api/config/schema — schema for every config field."""
        return await self._get("config/schema")

    async def get_config_raw(self) -> Any:
        """GET /api/config/raw — raw YAML text."""
        return await self._get("config/raw")

    async def put_config(self, config: dict[str, Any]) -> Any:
        """PUT /api/config — save a new configuration."""
        return await self._put("config", json={"config": config})

    async def put_config_raw(self, yaml_text: str) -> Any:
        """PUT /api/config/raw — save raw YAML text."""
        return await self._put("config/raw", json={"yaml_text": yaml_text})

    # ─── Environment Variables ────────────────────────────────────────────

    async def get_env(self, profile: str | None = None) -> Any:
        """GET /api/env — all env vars with metadata."""
        return await self._get("env", profile=profile)

    async def put_env(self, key: str, value: str) -> Any:
        """PUT /api/env — set an environment variable."""
        return await self._put("env", json={"key": key, "value": value})

    async def delete_env(self, key: str) -> None:
        """DELETE /api/env — remove an environment variable."""
        await self._delete("env", json={"key": key})

    # ─── Logs ─────────────────────────────────────────────────────────────

    async def get_logs(
        self,
        file: str | None = None,
        lines: int | None = None,
        level: str | None = None,
        component: str | None = None,
    ) -> Any:
        """GET /api/logs — log lines from the specified file."""
        return await self._get("logs", file=file, lines=lines, level=level, component=component)

    # ─── Analytics ────────────────────────────────────────────────────────

    async def get_usage_analytics(self, days: int = 30) -> Any:
        """GET /api/analytics/usage — token usage, cost, and session analytics."""
        return await self._get("analytics/usage", days=days)

    async def get_models_analytics(self, days: int = 30) -> Any:
        """GET /api/analytics/models — per-model analytics."""
        return await self._get("analytics/models", days=days)

    # ─── Cron Jobs ────────────────────────────────────────────────────────

    async def get_cron_jobs(self) -> Any:
        """GET /api/cron/jobs — all cron jobs."""
        return await self._get("cron/jobs")

    async def get_cron_job(self, job_id: str) -> Any:
        """GET /api/cron/jobs/{job_id} — single cron job."""
        return await self._get(f"cron/jobs/{job_id}")

    async def create_cron_job(
        self,
        prompt: str,
        schedule: str,
        name: str | None = None,
        deliver: str = "local",
    ) -> Any:
        """POST /api/cron/jobs — create a new cron job."""
        return await self._post(
            "cron/jobs",
            json={"prompt": prompt, "schedule": schedule, "name": name, "deliver": deliver},
        )

    async def update_cron_job(self, job_id: str, updates: dict[str, Any]) -> Any:
        """PUT /api/cron/jobs/{job_id} — update cron job fields."""
        return await self._put(f"cron/jobs/{job_id}", json={"updates": updates})

    async def pause_cron_job(self, job_id: str) -> Any:
        """POST /api/cron/jobs/{job_id}/pause."""
        return await self._post(f"cron/jobs/{job_id}/pause")

    async def resume_cron_job(self, job_id: str) -> Any:
        """POST /api/cron/jobs/{job_id}/resume."""
        return await self._post(f"cron/jobs/{job_id}/resume")

    async def trigger_cron_job(self, job_id: str) -> Any:
        """POST /api/cron/jobs/{job_id}/trigger."""
        return await self._post(f"cron/jobs/{job_id}/trigger")

    async def delete_cron_job(self, job_id: str) -> None:
        """DELETE /api/cron/jobs/{job_id}."""
        await self._delete(f"cron/jobs/{job_id}")

    # ─── Skills ───────────────────────────────────────────────────────────

    async def get_skills(self) -> Any:
        """GET /api/skills — all skills with enabled status."""
        return await self._get("skills")

    async def toggle_skill(self, name: str, enabled: bool) -> Any:
        """PUT /api/skills/toggle — enable or disable a skill."""
        return await self._put("skills/toggle", json={"name": name, "enabled": enabled})

    # ─── Toolsets ─────────────────────────────────────────────────────────

    async def get_toolsets(self) -> Any:
        """GET /api/tools/toolsets — all toolsets with status."""
        return await self._get("tools/toolsets")

    # ─── Model ────────────────────────────────────────────────────────────

    async def get_model_info(self) -> Any:
        """GET /api/model/info — resolved model metadata."""
        return await self._get("model/info")

    async def get_auxiliary_models(self) -> Any:
        """GET /api/model/auxiliary — current auxiliary task assignments."""
        return await self._get("model/auxiliary")

    async def set_model_assignment(
        self,
        scope: str,
        provider: str,
        model: str,
        task: str = "",
    ) -> Any:
        """POST /api/model/set — assign provider/model to main or auxiliary slot."""
        return await self._post(
            "model/set",
            json={"scope": scope, "provider": provider, "model": model, "task": task},
        )

    # ─── Profiles ─────────────────────────────────────────────────────────

    async def get_profiles(self) -> Any:
        """GET /api/profiles — list all profiles."""
        return await self._get("profiles")

    async def create_profile(
        self,
        name: str,
        clone_from_default: bool = False,
        no_skills: bool = False,
    ) -> Any:
        """POST /api/profiles — create a new profile."""
        return await self._post(
            "profiles",
            json={"name": name, "clone_from_default": clone_from_default, "no_skills": no_skills},
        )

    async def rename_profile(self, name: str, new_name: str) -> Any:
        """PATCH /api/profiles/{name} — rename a profile."""
        return await self._patch(f"profiles/{name}", json={"new_name": new_name})

    async def delete_profile(self, name: str) -> Any:
        """DELETE /api/profiles/{name} — delete a profile."""
        return await self._delete(f"profiles/{name}")

    async def get_profile_setup_command(self, name: str) -> Any:
        """GET /api/profiles/{name}/setup-command."""
        return await self._get(f"profiles/{name}/setup-command")

    async def get_profile_soul(self, name: str) -> Any:
        """GET /api/profiles/{name}/soul — SOUL.md content."""
        return await self._get(f"profiles/{name}/soul")

    async def update_profile_soul(self, name: str, content: str) -> Any:
        """PUT /api/profiles/{name}/soul — update SOUL.md."""
        return await self._put(f"profiles/{name}/soul", json={"content": content})

    # ─── Gateway / Update Actions ─────────────────────────────────────────

    async def restart_gateway(self) -> Any:
        """POST /api/gateway/restart — restart the Hermes gateway."""
        return await self._post("gateway/restart")

    async def wait_action_finished(
        self,
        name: str,
        *,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> Any:
        """Poll /api/actions/{name}/status until the background action exits."""
        deadline = asyncio.get_running_loop().time() + timeout
        status: Any = None
        while True:
            status = await self.get_action_status(name)
            if not isinstance(status, dict) or not status.get("running", False):
                return status
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Hermes action '{name}' did not finish within {timeout:g}s")
            await asyncio.sleep(poll_interval)

    async def update_hermes(self) -> Any:
        """POST /api/hermes/update — run hermes update."""
        return await self._post("hermes/update")

    async def get_action_status(self, name: str, lines: int = 200) -> Any:
        """GET /api/actions/{name}/status — tail action log."""
        return await self._get(f"actions/{name}/status", lines=lines)

    # ─── OAuth Providers ──────────────────────────────────────────────────

    async def get_oauth_providers(self, profile: str | None = None) -> Any:
        """GET /api/providers/oauth — list OAuth providers with status."""
        return await self._get("providers/oauth", profile=profile)

    async def disconnect_oauth_provider(self, provider_id: str) -> Any:
        """DELETE /api/providers/oauth/{provider_id}."""
        return await self._delete(f"providers/oauth/{provider_id}")

    async def start_oauth_login(self, provider_id: str) -> Any:
        """POST /api/providers/oauth/{provider_id}/start — initiate OAuth flow."""
        return await self._post(f"providers/oauth/{provider_id}/start", json={})

    async def submit_oauth_code(
        self, provider_id: str, session_id: str, code: str
    ) -> Any:
        """POST /api/providers/oauth/{provider_id}/submit — submit PKCE code."""
        return await self._post(
            f"providers/oauth/{provider_id}/submit",
            json={"session_id": session_id, "code": code},
        )

    async def poll_oauth_session(self, provider_id: str, session_id: str) -> Any:
        """GET /api/providers/oauth/{provider_id}/poll/{session_id}."""
        return await self._get(f"providers/oauth/{provider_id}/poll/{session_id}")

    async def cancel_oauth_session(self, session_id: str) -> Any:
        """DELETE /api/providers/oauth/sessions/{session_id}."""
        return await self._delete(f"providers/oauth/sessions/{session_id}")

    # ─── Dashboard Themes ─────────────────────────────────────────────────

    async def get_dashboard_themes(self) -> Any:
        """GET /api/dashboard/themes — available themes and active one."""
        return await self._get("dashboard/themes")

    async def set_dashboard_theme(self, name: str) -> Any:
        """PUT /api/dashboard/theme — set active theme."""
        return await self._put("dashboard/theme", json={"name": name})

    # ─── Dashboard Plugins ────────────────────────────────────────────────

    async def get_dashboard_plugins(self) -> Any:
        """GET /api/dashboard/plugins — discovered dashboard plugins."""
        return await self._get("dashboard/plugins")

    async def rescan_dashboard_plugins(self) -> Any:
        """GET /api/dashboard/plugins/rescan — force re-scan."""
        return await self._get("dashboard/plugins/rescan")

    async def get_plugins_hub(self) -> Any:
        """GET /api/dashboard/plugins/hub — unified agent plugins + extensions."""
        return await self._get("dashboard/plugins/hub")

    async def install_agent_plugin(
        self,
        identifier: str,
        force: bool = False,
        enable: bool = True,
    ) -> Any:
        """POST /api/dashboard/agent-plugins/install."""
        return await self._post(
            "dashboard/agent-plugins/install",
            json={"identifier": identifier, "force": force, "enable": enable},
        )

    async def enable_agent_plugin(self, name: str) -> Any:
        """POST /api/dashboard/agent-plugins/{name}/enable."""
        return await self._post(f"dashboard/agent-plugins/{name}/enable")

    async def disable_agent_plugin(self, name: str) -> Any:
        """POST /api/dashboard/agent-plugins/{name}/disable."""
        return await self._post(f"dashboard/agent-plugins/{name}/disable")

    async def update_agent_plugin(self, name: str) -> Any:
        """POST /api/dashboard/agent-plugins/{name}/update."""
        return await self._post(f"dashboard/agent-plugins/{name}/update")

    async def remove_agent_plugin(self, name: str) -> Any:
        """DELETE /api/dashboard/agent-plugins/{name}."""
        return await self._delete(f"dashboard/agent-plugins/{name}")

    async def set_plugin_visibility(self, name: str, hidden: bool) -> Any:
        """POST /api/dashboard/plugins/{name}/visibility."""
        return await self._post(
            f"dashboard/plugins/{name}/visibility",
            json={"hidden": hidden},
        )

    async def save_plugin_providers(
        self,
        memory_provider: str | None = None,
        context_engine: str | None = None,
    ) -> Any:
        """PUT /api/dashboard/plugin-providers."""
        body: dict[str, Any] = {}
        if memory_provider is not None:
            body["memory_provider"] = memory_provider
        if context_engine is not None:
            body["context_engine"] = context_engine
        return await self._put("dashboard/plugin-providers", json=body)

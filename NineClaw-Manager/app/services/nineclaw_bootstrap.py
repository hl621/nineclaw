"""Post-create bootstrap for nineclaw instances.

After a container is created and started, its Hermes dashboard is up but
unconfigured — no model selected, no provider API keys. Operators normally
fix this by hand (CLI commands, dashboard UI), which is awkward in an
automated cluster.

This module pushes a predefined config + env (sourced from settings) over
the dashboard REST API so a fresh container comes up *ready to use*:

    1. Wait until /api/status responds 2xx
    2. PUT every key from settings.nineclaw_default_env to /api/env
    3. (optional) Inject the inline custom OpenAI-compatible provider
       declared via NINECLAW_CUSTOM_PROVIDER_* settings directly into the
       top-level ``model`` block of the pushed config — no
       ``custom_providers[]`` entry, hermes treats it as a one-off endpoint.
    4. PUT settings.nineclaw_default_config (with the model block merged
       in) to /api/config
    5. (optional) POST /api/gateway/restart so the gateway picks up the new
       model assignment for new sessions

Per-instance overrides can be supplied at create time and take precedence
over the defaults from settings.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.nineclaw_topology import NINECLAW_SERVICES, render_route

logger = logging.getLogger(__name__)


class BootstrapError(Exception):
    """Raised when bootstrapping a nineclaw instance fails."""


def _dashboard_route_template() -> str:
    """Return the configured route template for the dashboard service."""
    for svc in NINECLAW_SERVICES:
        if svc.name == "dashboard":
            return svc.route_template
    raise RuntimeError("Dashboard service not declared in NINECLAW_SERVICES")


def build_dashboard_base_url(instance_id: str) -> str:
    """Compose the Traefik-fronted dashboard base URL for an instance."""
    prefix = render_route(_dashboard_route_template(), instance_id)
    return f"{settings.resolved_manager_traefik_url}{prefix}"


def _gateway_route_template() -> str:
    """Return the configured route template for the gateway service."""
    for svc in NINECLAW_SERVICES:
        if svc.name == "gateway":
            return svc.route_template
    raise RuntimeError("Gateway service not declared in NINECLAW_SERVICES")


def build_gateway_base_url(instance_id: str) -> str:
    """Compose the Traefik-fronted Hermes Gateway base URL for an instance."""
    prefix = render_route(_gateway_route_template(), instance_id)
    return f"{settings.resolved_manager_traefik_url}{prefix}"


def _webui_route_template() -> str:
    """Return the configured route template for the webui service."""
    for svc in NINECLAW_SERVICES:
        if svc.name == "webui":
            return svc.route_template
    raise RuntimeError("WebUI service not declared in NINECLAW_SERVICES")


def build_webui_api_base_url(instance_id: str) -> str:
    """Compose the Traefik-fronted Hermes WebUI API base URL for an instance."""
    prefix = render_route(_webui_route_template(), instance_id)
    return f"{settings.resolved_manager_traefik_url}{prefix}/api"


def _build_default_model_block() -> dict[str, Any] | None:
    """Render the inline ``model`` block from NINECLAW_CUSTOM_PROVIDER_* settings.

    Produces the shape::

        model:
          default: <model_id>
          provider: <name>          # typically "custom"
          base_url: <base_url>
          api_key:  <api_key>

    All four fields must be non-empty; otherwise this returns None and the
    bootstrap step leaves the dashboard's ``model`` block alone.
    """
    name = settings.nineclaw_custom_provider_name.strip()
    base_url = settings.nineclaw_custom_provider_base_url.strip()
    api_key = settings.nineclaw_custom_provider_api_key.strip()
    model = settings.nineclaw_custom_provider_model.strip()

    if not (name and base_url and api_key and model):
        return None

    return {
        "default": model,
        "provider": name,
        "base_url": base_url,
        "api_key": api_key,
    }


async def _wait_until_dashboard_ready(
    svc: HermesService, *, timeout: float, poll_interval: float = 1.0
) -> None:
    """Poll /api/status until it responds successfully or timeout elapses.

    Routing through Traefik means the first few attempts can fail with 404
    (Traefik hasn't picked up the new container labels yet) or connection
    errors (gateway still booting).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last_error: Exception | None = None
    attempts = 0

    while asyncio.get_event_loop().time() < deadline:
        attempts += 1
        try:
            await svc.get_status()
            logger.info("Dashboard ready after %d attempt(s)", attempts)
            return
        except Exception as exc:
            last_error = exc
            if attempts == 1 or attempts % 5 == 0:
                logger.info(
                    "Waiting for dashboard readiness: attempt=%d timeout=%.0fs last_error=%s",
                    attempts,
                    timeout,
                    exc,
                )
            await asyncio.sleep(poll_interval)

    raise BootstrapError(
        f"Dashboard did not become ready within {timeout:.0f}s "
        f"(last error: {last_error})"
    )


async def wait_until_instance_dashboard_ready(instance_id: str, *, timeout: float | None = None) -> None:
    """Wait until a created/restarted instance dashboard accepts API traffic."""
    async with HermesService(
        base_url=build_dashboard_base_url(instance_id),
        api_key=settings.nineclaw_token,
    ) as svc:
        await _wait_until_dashboard_ready(
            svc,
            timeout=timeout or settings.nineclaw_bootstrap_timeout,
        )


async def bootstrap_instance(
    instance_id: str,
    *,
    config_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, str] | None = None,
    restart_gateway: bool | None = None,
) -> None:
    """Apply default config + env to a freshly created nineclaw instance.

    Raises BootstrapError if the dashboard never becomes reachable or if a
    config/env push fails — the caller decides whether to keep the
    container or roll it back.
    """
    base_url = build_dashboard_base_url(instance_id)
    api_key = settings.nineclaw_token

    env_to_push: dict[str, str] = {**settings.nineclaw_default_env, **(env_overrides or {})}
    config_to_push: dict[str, Any] = {
        **settings.nineclaw_default_config,
        **(config_overrides or {}),
    }

    # Inline model block from NINECLAW_CUSTOM_PROVIDER_* settings. Caller
    # overrides on `model` still win — only fill it in if the merged config
    # doesn't already define one.
    default_model_block = _build_default_model_block()
    if default_model_block is not None and not config_to_push.get("model"):
        config_to_push["model"] = default_model_block

    logger.info(
        "Bootstrapping instance %s: %d env var(s), %d config key(s), "
        "default_model=%s dashboard_url=%s config_keys=%s env_keys=%s",
        instance_id,
        len(env_to_push),
        len(config_to_push),
        (default_model_block or {}).get("default") or "none",
        base_url,
        sorted(config_to_push.keys()),
        sorted(env_to_push.keys()),
    )

    async with HermesService(base_url=base_url, api_key=api_key) as svc:
        await _wait_until_dashboard_ready(
            svc, timeout=settings.nineclaw_bootstrap_timeout
        )

        if not env_to_push and not config_to_push:
            logger.info(
                "No default config/env defined; dashboard is ready for instance %s",
                instance_id,
            )
            return

        # Push env vars first — config can reference provider keys.
        for key, value in env_to_push.items():
            try:
                logger.info("Bootstrap put env: instance=%s key=%s", instance_id, key)
                await svc.put_env(key, value)
            except HermesError as exc:
                raise BootstrapError(
                    f"Failed to set env var '{key}' on instance {instance_id}: {exc}"
                ) from exc

        if config_to_push:
            try:
                logger.info(
                    "Bootstrap put config: instance=%s keys=%s",
                    instance_id,
                    sorted(config_to_push.keys()),
                )
                await svc.put_config(config_to_push)
            except HermesError as exc:
                raise BootstrapError(
                    f"Failed to PUT /api/config on instance {instance_id}: {exc}"
                ) from exc

        should_restart_gateway = (
            settings.nineclaw_bootstrap_restart_gateway
            if restart_gateway is None
            else restart_gateway
        )
        if should_restart_gateway and config_to_push:
            try:
                logger.info("Bootstrap restart gateway: instance=%s", instance_id)
                await svc.restart_gateway()
            except HermesError as exc:
                # Non-fatal: config is already saved; the gateway will pick
                # it up on its next natural restart.
                logger.warning(
                    "gateway/restart failed on instance %s (config still saved): %s",
                    instance_id,
                    exc,
                )

    logger.info("Instance %s bootstrapped successfully", instance_id)

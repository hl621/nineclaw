"""Read / apply per-instance RAG and WebSearch plugin settings."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.knowledge_deploy_service import (
    ENV_QYRAG_DATASETS,
    RAGFLOW_PLUGIN_ID,
    build_external_knowledge_block,
    build_rag_deploy_env,
    ensure_ragflow_plugin_enabled,
    restart_gateway_and_wait,
    rewrite_hermes_dotenv_var_utf8,
)

if TYPE_CHECKING:
    from app.services.docker_service import DockerService
from app.services.nineclaw_bootstrap import build_dashboard_base_url
from app.services.websearch_deploy_service import (
    ENV_WEBSEARCH_INCLUDE_SOURCES,
    WEBSEARCH_PLUGIN_ID,
    build_websearch_deploy_env,
    merge_websearch_config,
)

logger = logging.getLogger(__name__)


def _as_record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _env_live_value(env: Any, key: str) -> str | None:
    """Best-effort extract of a live env value from Dashboard ``GET /api/env``.

    Hermes often returns schema-only metadata (no live values). Prefer explicit
    ``value`` / non-redacted ``redacted_value`` when present.
    """
    record = _as_record(env)
    if not record:
        return None
    meta = record.get(key)
    if isinstance(meta, str):
        text = meta.strip()
        return text or None
    meta_rec = _as_record(meta)
    if not meta_rec:
        return None
    for field in ("value", "current", "raw", "redacted_value"):
        raw = meta_rec.get(field)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        # Skip fully masked secrets like "***"
        if field == "redacted_value" and set(text) <= {"*", "•", "·", " "}:
            continue
        return text
    return None


def _walk_plugin_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        rec = _as_record(node)
        if not rec:
            return
        name = (
            rec.get("name")
            or rec.get("id")
            or rec.get("plugin_id")
            or rec.get("identifier")
        )
        if isinstance(name, str) and name.strip():
            nodes.append(rec)
        for key in (
            "plugins",
            "agent_plugins",
            "items",
            "installed",
            "available",
            "extensions",
            "hub",
        ):
            if key in rec:
                walk(rec.get(key))

    walk(payload)
    return nodes


def plugin_enabled_from_hub(hub: Any, plugin_id: str) -> bool | None:
    """Return True/False when hub reports the plugin; None if unknown."""
    target = plugin_id.strip().lower()
    if not target:
        return None
    for node in _walk_plugin_nodes(hub):
        name = str(
            node.get("name")
            or node.get("id")
            or node.get("plugin_id")
            or node.get("identifier")
            or ""
        ).strip()
        if name.lower() != target:
            continue
        for key in ("enabled", "is_enabled", "active"):
            if key in node:
                return bool(node.get(key))
        status = str(
            node.get("status")
            or node.get("state")
            or node.get("runtime_status")
            or ""
        ).strip().lower()
        if status in {"enabled", "active", "on", "running"}:
            return True
        if status in {"disabled", "inactive", "off", "stopped"}:
            return False
        if "enabled" in node or "disabled" in node:
            return bool(node.get("enabled")) and not bool(node.get("disabled"))
    return None


def knowledge_ids_from_config(config: Any) -> list[str]:
    rec = _as_record(config) or {}
    ext = _as_record(rec.get("external_knowledge")) or {}
    raw_ids = ext.get("dataset_ids")
    if not isinstance(raw_ids, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_ids:
        kid = str(item or "").strip()
        if kid and kid not in seen:
            seen.add(kid)
            out.append(kid)
    return out


def knowledge_ids_from_qyrag_datasets(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in parsed.values():
        kid = str(value or "").strip()
        if kid and kid not in seen:
            seen.add(kid)
            out.append(kid)
    return out


def source_ids_from_include_sources(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        sid = part.strip()
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


async def read_instance_rag_config(instance_id: str) -> dict[str, Any]:
    base_url = build_dashboard_base_url(instance_id)
    async with HermesService(base_url=base_url, api_key=settings.nineclaw_token) as svc:

        async def get_plugins_hub_optional() -> Any:
            try:
                return await svc.get_plugins_hub()
            except HermesError as exc:
                logger.info(
                    "rag config: plugins hub unavailable for %s: %s",
                    instance_id,
                    exc.detail,
                )
                return None

        config, env, hub = await asyncio.gather(
            svc.get_config(),
            svc.get_env(),
            get_plugins_hub_optional(),
        )

    knowledge_ids = knowledge_ids_from_config(config)
    if not knowledge_ids:
        knowledge_ids = knowledge_ids_from_qyrag_datasets(
            _env_live_value(env, "QYRAG_DATASETS")
        )
    enabled = plugin_enabled_from_hub(hub, RAGFLOW_PLUGIN_ID)
    return {
        "enabled": True if enabled is None else enabled,
        "plugin_id": RAGFLOW_PLUGIN_ID,
        "knowledge_ids": knowledge_ids,
        "plugin_status_known": enabled is not None,
    }


async def apply_instance_rag_config(
    instance_id: str,
    *,
    enabled: bool,
    knowledge_ids: list[str],
    knowledge_name_map: dict[str, str] | None,
    rag_base_url: str,
    rag_api_key: str,
    docker_service: DockerService | None = None,
    container_id: str | None = None,
) -> dict[str, Any]:
    base_url = build_dashboard_base_url(instance_id)
    ids = [str(kid).strip() for kid in knowledge_ids if str(kid).strip()]

    async with HermesService(base_url=base_url, api_key=settings.nineclaw_token) as svc:
        if not enabled:
            # Preserve .env / external_knowledge; only disable the plugin.
            existing_ids = knowledge_ids_from_config(await svc.get_config())
            try:
                await svc.disable_agent_plugin(RAGFLOW_PLUGIN_ID)
            except HermesError as exc:
                # Plugin may not be installed yet — treat as already off.
                if exc.status_code >= 500:
                    raise
                logger.info(
                    "rag disable skipped for %s: %s",
                    instance_id,
                    exc.detail,
                )
            await restart_gateway_and_wait(svc)
            return {
                "enabled": False,
                "plugin_id": RAGFLOW_PLUGIN_ID,
                "knowledge_ids": existing_ids,
                "restart": "gateway",
            }

        current = await svc.get_config()
        if not isinstance(current, dict):
            current = {}
        current["external_knowledge"] = build_external_knowledge_block(
            base_url=rag_base_url,
            api_key=rag_api_key,
            knowledge_ids=ids,
        )
        await svc.put_config(current)

        env_vars = build_rag_deploy_env(
            base_url=rag_base_url,
            api_key=rag_api_key,
            knowledge_ids=ids,
            knowledge_name_map=knowledge_name_map,
            always_include_datasets=True,
        )
        for key, value in env_vars.items():
            # Hermes PUT /api/env strips non-ASCII → empty JSON keys.
            # Put an ASCII-safe form first so .env never stays as {"": id}.
            put_value = value
            if key == ENV_QYRAG_DATASETS:
                try:
                    put_value = json.dumps(json.loads(value), ensure_ascii=True)
                except (TypeError, ValueError):
                    put_value = value
            await svc.put_env(key, put_value)

        # Rewrite QYRAG_DATASETS as UTF-8 Chinese via Docker exec so
        # `cat /opt/data/.env` shows {"策略分析": "..."} instead of \uXXXX.
        datasets_value = env_vars.get(ENV_QYRAG_DATASETS)
        if (
            datasets_value
            and docker_service is not None
            and (container_id or "").strip()
        ):
            try:
                await rewrite_hermes_dotenv_var_utf8(
                    docker_service,
                    container_id.strip(),
                    ENV_QYRAG_DATASETS,
                    datasets_value,
                )
            except Exception as rewrite_exc:
                logger.warning(
                    "rag config: utf-8 dotenv rewrite failed for %s: %s "
                    "(ASCII-safe QYRAG_DATASETS already written via Hermes)",
                    instance_id,
                    rewrite_exc,
                )

        await ensure_ragflow_plugin_enabled(svc)
        await restart_gateway_and_wait(svc)

    return {
        "enabled": True,
        "plugin_id": RAGFLOW_PLUGIN_ID,
        "knowledge_ids": ids,
        "restart": "gateway",
    }


async def read_instance_websearch_config(instance_id: str) -> dict[str, Any]:
    base_url = build_dashboard_base_url(instance_id)
    async with HermesService(base_url=base_url, api_key=settings.nineclaw_token) as svc:
        env = await svc.get_env()
        hub: Any = None
        try:
            hub = await svc.get_plugins_hub()
        except HermesError as exc:
            logger.info(
                "websearch config: plugins hub unavailable for %s: %s",
                instance_id,
                exc.detail,
            )

    source_ids = source_ids_from_include_sources(
        _env_live_value(env, ENV_WEBSEARCH_INCLUDE_SOURCES)
    )
    enabled = plugin_enabled_from_hub(hub, WEBSEARCH_PLUGIN_ID)
    return {
        "enabled": True if enabled is None else enabled,
        "plugin_id": WEBSEARCH_PLUGIN_ID,
        "source_ids": source_ids,
        "plugin_status_known": enabled is not None,
    }


async def apply_instance_websearch_config(
    instance_id: str,
    *,
    enabled: bool,
    source_ids: list[str],
    restart_container,
) -> dict[str, Any]:
    """``restart_container`` is an async callable ``(instance_id) -> None``."""
    base_url = build_dashboard_base_url(instance_id)
    ids = [str(sid).strip() for sid in source_ids if str(sid).strip()]

    async with HermesService(base_url=base_url, api_key=settings.nineclaw_token) as svc:
        if not enabled:
            # Preserve INCLUDE_SOURCES in .env; only disable the plugin.
            try:
                await svc.disable_agent_plugin(WEBSEARCH_PLUGIN_ID)
            except HermesError as exc:
                if exc.status_code >= 500:
                    raise
                logger.info(
                    "websearch disable skipped for %s: %s",
                    instance_id,
                    exc.detail,
                )
        else:
            current = await svc.get_config()
            await svc.put_config(merge_websearch_config(current))
            for key, value in build_websearch_deploy_env(ids).items():
                await svc.put_env(key, value)
            await svc.enable_agent_plugin(WEBSEARCH_PLUGIN_ID)

    await restart_container(instance_id)
    return {
        "enabled": enabled,
        "plugin_id": WEBSEARCH_PLUGIN_ID,
        "source_ids": ids,
        "restart": "container",
    }

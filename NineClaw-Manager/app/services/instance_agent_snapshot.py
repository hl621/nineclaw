"""Persist Manager-owned, secret-free Agent resource snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import ServiceInstance

MANAGER_RESOURCE_SNAPSHOT_KEY: Final = "manager_resource_snapshot"
_UNSET: Final = object()


class InstanceAgentSnapshotNotFoundError(LookupError):
    """Raised when a target instance disappears before its snapshot is stored."""


def read_manager_resource_snapshot(config: Any) -> dict[str, Any]:
    """Return a safe public projection of the Manager resource snapshot.

    Legacy instances have no Manager-owned snapshot.  Their resource state is
    intentionally reported as unknown instead of being inferred from Hermes.
    """

    raw_snapshot = (
        config.get(MANAGER_RESOURCE_SNAPSHOT_KEY)
        if isinstance(config, Mapping)
        else None
    )
    if (
        not isinstance(raw_snapshot, Mapping)
        or _sanitize_timestamp(raw_snapshot.get("config_updated_at")) is None
    ):
        return {
            "snapshot_state": "unknown",
            "model": None,
            "knowledge_bases": [],
            "mcps": [],
            "skills": [],
            "config_updated_at": None,
        }

    return {
        "snapshot_state": "known",
        **_sanitize_snapshot(raw_snapshot),
    }


def merge_manager_resource_snapshot(
    config: Any,
    *,
    providers: Any = _UNSET,
    model: Any = _UNSET,
    knowledge_bases: Any = _UNSET,
    mcps: Any = _UNSET,
    skills: Any = _UNSET,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """Safely merge one or more Manager-configured resource updates.

    Knowledge deployment replaces the selected dataset set.  MCP and Skill
    deployment are additive in Hermes, so their Manager-known entries merge
    by stable ID/slug.  No untrusted config values are copied into the
    snapshot.
    """

    merged_config = deepcopy(dict(config)) if isinstance(config, Mapping) else {}
    current = read_manager_resource_snapshot(merged_config)
    raw_snapshot = merged_config.get(MANAGER_RESOURCE_SNAPSHOT_KEY)
    snapshot = {
        "model": current["model"],
        "knowledge_bases": current["knowledge_bases"],
        "mcps": current["mcps"],
        "skills": current["skills"],
    }

    # Absence means a legacy instance whose provider state has not been
    # backfilled yet.  Preserve that distinction until an explicit provider
    # deployment (including an empty list) replaces it.
    if isinstance(raw_snapshot, Mapping) and "providers" in raw_snapshot:
        snapshot["providers"] = _sanitize_providers(
            raw_snapshot.get("providers"), strict=True
        )

    if providers is not _UNSET:
        snapshot["providers"] = _sanitize_providers(providers, strict=True)
    if model is not _UNSET:
        snapshot["model"] = _sanitize_model(model)
    if knowledge_bases is not _UNSET:
        snapshot["knowledge_bases"] = _sanitize_knowledge_bases(knowledge_bases)
    if mcps is not _UNSET:
        snapshot["mcps"] = _merge_mcps(snapshot["mcps"], _sanitize_mcps(mcps))
    if skills is not _UNSET:
        snapshot["skills"] = _merge_skills(snapshot["skills"], _sanitize_skills(skills))

    snapshot["config_updated_at"] = _snapshot_timestamp(updated_at)
    merged_config[MANAGER_RESOURCE_SNAPSHOT_KEY] = snapshot
    return merged_config


async def persist_manager_resource_snapshot(
    session: AsyncSession,
    *,
    tenant_id: str,
    instance_id: str,
    providers: Any = _UNSET,
    model: Any = _UNSET,
    knowledge_bases: Any = _UNSET,
    mcps: Any = _UNSET,
    skills: Any = _UNSET,
) -> ServiceInstance:
    """Merge a snapshot update under an instance-row lock.

    The caller owns the transaction and must commit only after the remote
    deployment has reached its success boundary.
    """

    instance = await lock_instance_for_snapshot(
        session,
        tenant_id=tenant_id,
        instance_id=instance_id,
    )

    instance.config = merge_manager_resource_snapshot(
        instance.config,
        providers=providers,
        model=model,
        knowledge_bases=knowledge_bases,
        mcps=mcps,
        skills=skills,
    )
    instance.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(instance)
    return instance


async def lock_instance_for_snapshot(
    session: AsyncSession,
    *,
    tenant_id: str,
    instance_id: str,
) -> ServiceInstance:
    """Lock and refresh one tenant-owned instance in the caller transaction."""

    statement = (
        select(ServiceInstance)
        .where(
            ServiceInstance.id == instance_id,
            ServiceInstance.tenant_id == tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    result = await session.execute(statement)
    instance = result.scalar_one_or_none()
    if instance is None:
        raise InstanceAgentSnapshotNotFoundError(
            f"instance '{instance_id}' not found for tenant '{tenant_id}'"
        )

    return instance


async def persist_legacy_provider_snapshot_if_missing(
    session: AsyncSession,
    *,
    tenant_id: str,
    instance_id: str,
    providers: Any,
) -> tuple[ServiceInstance, list[dict[str, Any]], bool]:
    """Backfill legacy providers without overwriting a concurrent deployment."""

    instance = await lock_instance_for_snapshot(
        session,
        tenant_id=tenant_id,
        instance_id=instance_id,
    )
    current = read_instance_provider_snapshot(instance.config)
    if current is not None:
        return instance, current, False

    instance.config = merge_manager_resource_snapshot(
        instance.config,
        providers=providers,
    )
    instance.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(instance)
    saved = read_instance_provider_snapshot(instance.config)
    assert saved is not None
    return instance, saved, True


def read_instance_provider_snapshot(config: Any) -> list[dict[str, Any]] | None:
    """Return an instance provider snapshot, or ``None`` for legacy data."""

    raw_snapshot = (
        config.get(MANAGER_RESOURCE_SNAPSHOT_KEY)
        if isinstance(config, Mapping)
        else None
    )
    if not isinstance(raw_snapshot, Mapping) or "providers" not in raw_snapshot:
        return None
    return _sanitize_providers(raw_snapshot.get("providers"), strict=True)


def extract_provider_snapshot_from_hermes_config(
    config: Any,
) -> list[dict[str, Any]]:
    """Extract the secret-free provider catalog from one Hermes config."""

    if not isinstance(config, Mapping):
        raise ValueError("Dashboard config must be an object")
    custom_providers = config.get("custom_providers", [])
    if not isinstance(custom_providers, list):
        raise ValueError("Dashboard custom_providers must be a list")
    return _sanitize_providers(custom_providers, strict=True)


def _sanitize_snapshot(raw_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": _sanitize_model(raw_snapshot.get("model")),
        "knowledge_bases": _sanitize_knowledge_bases(
            raw_snapshot.get("knowledge_bases")
        ),
        "mcps": _sanitize_mcps(raw_snapshot.get("mcps")),
        "skills": _sanitize_skills(raw_snapshot.get("skills")),
        "config_updated_at": _sanitize_timestamp(raw_snapshot.get("config_updated_at")),
    }


def _sanitize_model(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    provider = _clean_text(value.get("provider"))
    model = _clean_text(value.get("model"))
    if not provider or not model:
        return None
    return {"provider": provider, "model": model}


def _sanitize_providers(
    value: Any,
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        if strict:
            raise ValueError("Provider snapshot must be a list")
        return []
    items: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    for raw_item in value:
        if not isinstance(raw_item, Mapping):
            if strict:
                raise ValueError("Provider snapshot entries must be objects")
            continue
        name = _clean_text(raw_item.get("name"))
        if not name:
            if strict:
                raise ValueError("Provider snapshot entry name is invalid")
            continue
        if "models" not in raw_item:
            if strict:
                raise ValueError("Provider snapshot entry models are required")
            models_value = []
        else:
            models_value = raw_item.get("models")
        if isinstance(models_value, Mapping):
            model_candidates = models_value.keys()
        elif isinstance(models_value, list):
            model_candidates = models_value
        else:
            if strict:
                raise ValueError("Provider snapshot entry models are invalid")
            model_candidates = []
        models = _clean_model_names(list(model_candidates), strict=strict)
        key = name.casefold()
        existing_index = indexes.get(key)
        if existing_index is None:
            indexes[key] = len(items)
            items.append({"name": name, "models": models})
            continue
        existing = items[existing_index]
        existing["models"] = _clean_model_names([*existing["models"], *models])
    return items


def _clean_model_names(value: Any, *, strict: bool = False) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    unique: set[str] = set()
    for model in value:
        if not isinstance(model, str) or not model.strip():
            if strict:
                raise ValueError("Provider snapshot model names are invalid")
            continue
        unique.add(model.strip())
    return sorted(unique, key=lambda model: (model.casefold(), model))


def _sanitize_knowledge_bases(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_item in _mapping_items(value):
        knowledge_id = _clean_text(raw_item.get("id"))
        name = _clean_text(raw_item.get("name"))
        if not knowledge_id or not name or knowledge_id in seen_ids:
            continue
        seen_ids.add(knowledge_id)
        items.append({"id": knowledge_id, "name": name})
    return items


def _sanitize_mcps(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for raw_item in _mapping_items(value):
        mcp_id = _clean_text(raw_item.get("id"))
        name = _clean_text(raw_item.get("name"))
        if not mcp_id or not name or mcp_id in seen_ids or name in seen_names:
            continue
        seen_ids.add(mcp_id)
        seen_names.add(name)
        enabled = raw_item.get("enabled")
        items.append(
            {
                "id": mcp_id,
                "name": name,
                "enabled": enabled if isinstance(enabled, bool) else True,
            }
        )
    return items


def _sanitize_skills(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_slugs: set[str] = set()
    for raw_item in _mapping_items(value):
        slug = _clean_text(raw_item.get("slug"))
        name = _clean_text(raw_item.get("name"))
        if not slug or not name or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        items.append({"slug": slug, "name": name})
    return items


def _merge_mcps(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(existing)
    for update in updates:
        merged = [
            item
            for item in merged
            if item["id"] != update["id"] and item["name"] != update["name"]
        ]
        merged.append(update)
    return merged


def _merge_skills(
    existing: list[dict[str, str]], updates: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged = list(existing)
    for update in updates:
        merged = [item for item in merged if item["slug"] != update["slug"]]
        merged.append(update)
    return merged


def _mapping_items(value: Any) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _snapshot_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value

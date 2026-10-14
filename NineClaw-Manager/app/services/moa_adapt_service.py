"""Adapt Hermes MoA presets to deployed custom_providers when built-in providers lack credentials."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_BUILTIN_SLUGS = {"openrouter", "openai-codex"}


def _models_for_provider(config: dict[str, Any], provider: str) -> list[str]:
    for entry in config.get("custom_providers") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("name") != provider:
            continue
        models = entry.get("models") or {}
        if isinstance(models, dict):
            return list(models.keys())
        if isinstance(models, list):
            return [str(item) for item in models if item]
    return []


def _pick_fallback(provider: str, available: list[str]) -> dict[str, str] | None:
    if not available:
        return None

    def prefer(names: list[str]) -> str | None:
        for name in names:
            if name in available:
                return name
        return None

    aggregator = prefer(
        ["MiniMax-M2.7", "MiniMax-M3", "Kimi-K2.6", "Kimi-K2.5", "GLM-5.2", "GLM-5.1", "GLM-5"]
    ) or available[0]
    ref_a = prefer(["Kimi-K2.5", "Kimi-K2.6", "GLM-5", "GLM-5.1", "GLM-5.2"]) or (
        next((m for m in available if m != aggregator), available[0])
    )
    ref_b = prefer(["GLM-5", "GLM-5.1", "GLM-5.2", "Kimi-K2.5"]) or (
        next((m for m in available if m not in {aggregator, ref_a}), ref_a)
    )
    return {"provider": provider, "ref_a": ref_a, "ref_b": ref_b, "aggregator": aggregator}


def _needs_builtin_credentials(preset: dict[str, Any]) -> bool:
    refs = preset.get("reference_models") or []
    agg = preset.get("aggregator") or {}
    for item in [*refs, agg]:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "")
        if provider in _BUILTIN_SLUGS:
            return True
    return False


def adapt_moa_config_to_instance(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (config, changed). Rewrites moa presets to custom_providers when needed."""
    moa = config.get("moa")
    if not isinstance(moa, dict):
        return config, False

    custom_providers = config.get("custom_providers") or []
    provider_name = None
    for entry in custom_providers:
        if isinstance(entry, dict) and entry.get("name"):
            if _models_for_provider(config, str(entry["name"])):
                provider_name = str(entry["name"])
                break
    if not provider_name:
        return config, False

    available = _models_for_provider(config, provider_name)
    fallback = _pick_fallback(provider_name, available)
    if not fallback:
        return config, False

    next_config = deepcopy(config)
    next_moa = deepcopy(moa)
    presets = next_moa.get("presets")
    if not isinstance(presets, dict):
        return config, False

    changed = False
    for name, preset in presets.items():
        if not isinstance(preset, dict) or not _needs_builtin_credentials(preset):
            continue
        preset = deepcopy(preset)
        preset["reference_models"] = [
            {"provider": provider_name, "model": fallback["ref_a"]},
            {"provider": provider_name, "model": fallback["ref_b"]},
        ]
        preset["aggregator"] = {
            "provider": provider_name,
            "model": fallback["aggregator"],
        }
        preset.setdefault("reference_max_tokens", 600)
        presets[name] = preset
        changed = True

    if not changed:
        return config, False

    next_moa["presets"] = presets
    next_config["moa"] = next_moa
    return next_config, True

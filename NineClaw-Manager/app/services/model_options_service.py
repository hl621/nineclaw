"""Build the selectable model catalog from a Hermes ``/api/config`` response."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _provider_id(name: str) -> str:
    """Return the provider id understood by Hermes session model selectors."""
    return f"custom:{'-'.join(name.casefold().split())}"


def _model_names(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        candidates = value.keys()
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        return []
    names = {_text(item) for item in candidates}
    names.discard("")
    return sorted(names, key=lambda item: (item.casefold(), item))


def build_model_options_from_config(config: Any) -> dict[str, Any]:
    """Format only ``custom_providers`` and enabled ``moa.presets``.

    Secret-bearing provider fields such as ``api_key`` and ``base_url`` are
    deliberately ignored and can never enter the returned payload.
    """
    if not isinstance(config, Mapping):
        raise ValueError("Dashboard config must be an object")
    custom_providers = config.get("custom_providers", [])
    if not isinstance(custom_providers, list):
        raise ValueError("Dashboard custom_providers must be a list")

    groups: list[dict[str, Any]] = []
    for entry in custom_providers:
        if not isinstance(entry, Mapping):
            raise ValueError("Dashboard custom_providers entries must be objects")
        name = _text(entry.get("name"))
        if not name:
            raise ValueError("Dashboard custom provider name is required")
        provider_id = _provider_id(name)
        names = _model_names(entry.get("models"))
        model_rows = [
            {
                "id": model,
                "label": model,
            }
            for model in names
        ]
        groups.append(
            {
                "provider": name,
                "provider_id": provider_id,
                "models": model_rows,
            }
        )

    moa = config.get("moa")
    presets = moa.get("presets") if isinstance(moa, Mapping) else None
    moa_names = sorted(
        (
            _text(name)
            for name, preset in (presets.items() if isinstance(presets, Mapping) else [])
            if isinstance(preset, Mapping) and preset.get("enabled") is not False
        ),
        key=lambda item: (item.casefold(), item),
    )
    moa_names = [name for name in moa_names if name]
    if moa_names:
        moa_models = [
            {
                "id": preset,
                "label": f"MoA: {preset}",
            }
            for preset in moa_names
        ]
        groups.append(
            {
                "provider": "Mixture of Agents",
                "provider_id": "moa",
                "models": moa_models,
            }
        )

    return {"groups": groups}

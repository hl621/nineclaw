"""Merge the fixed workspace MCP server into the persisted Hermes config."""

from __future__ import annotations

import os
import pwd
import stat
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


_BRIDGE_ENV_KEYS = (
    "NINECLAW_MANAGER_URL",
    "NINECLAW_WORKSPACE_INSTANCE_ID",
    "NINECLAW_WORKSPACE_BRIDGE_TOKEN",
    "NINECLAW_WORKSPACE_DIR",
)


def workspace_bridge_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Require Manager-issued identity and credential before exposing the MCP."""
    values = os.environ if environment is None else environment
    return all(str(values.get(key, "")).strip() for key in _BRIDGE_ENV_KEYS)


def merge_workspace_mcp_config(
    config: dict[str, Any], template: dict[str, Any], *, enabled: bool
) -> dict[str, Any]:
    result = dict(config)
    raw_servers = result.get("mcp_servers")
    servers = dict(raw_servers) if isinstance(raw_servers, dict) else {}
    if enabled:
        workspace = dict(template.get("mcp_servers") or {}).get(
            "workflow_workspace"
        )
        if not isinstance(workspace, dict):
            raise ValueError("workspace MCP 模板无效")
        servers["workflow_workspace"] = workspace
    elif "workflow_workspace" not in servers:
        return result
    else:
        del servers["workflow_workspace"]
    result["mcp_servers"] = servers
    return result


def _set_config_owner(path: Path, owner: os.stat_result | None) -> None:
    """Keep a new persisted config readable by the Hermes runtime user."""
    if owner is not None:
        os.chown(path, owner.st_uid, owner.st_gid)
        os.chmod(path, stat.S_IMODE(owner.st_mode))
        return
    hermes = pwd.getpwnam("hermes")
    os.chown(path, hermes.pw_uid, hermes.pw_gid)


def main() -> None:
    home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    config_path = home / "config.yaml"
    template_path = Path("/opt/nineclaw/workspace-hermes-config.yaml")
    current = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    current = current or {}
    template = yaml.safe_load(template_path.read_text())
    if not isinstance(current, dict) or not isinstance(template, dict):
        raise ValueError("Hermes 配置必须是 YAML 对象")
    merged = merge_workspace_mcp_config(
        current, template, enabled=workspace_bridge_enabled()
    )
    if merged == current:
        return
    home.mkdir(parents=True, exist_ok=True)
    owner = config_path.stat() if config_path.exists() else None
    with NamedTemporaryFile("w", encoding="utf-8", dir=home, delete=False) as handle:
        yaml.safe_dump(merged, handle, allow_unicode=True, sort_keys=False)
        temporary = Path(handle.name)
    _set_config_owner(temporary, owner)
    temporary.replace(config_path)


if __name__ == "__main__":
    main()

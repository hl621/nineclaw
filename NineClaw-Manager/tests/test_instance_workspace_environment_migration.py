"""Regression checks for persisted Workspace environment cleanup migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260723_000003_025_remove_persisted_workspace_environment.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "remove_persisted_workspace_environment_025", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_sql(statement: object) -> str:
    return " ".join(str(statement).split())


def test_workspace_environment_migration_removes_workspace_runtime_keys(
    monkeypatch,
):
    migration = _migration_module()
    statements: list[object] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert migration.revision == "025"
    assert migration.down_revision == "024"
    assert migration._WORKSPACE_ENV_PREFIX == "NINECLAW_WORKSPACE_"
    assert "NINECLAW_WORKSPACE_BRIDGE_TOKEN".startswith(migration._WORKSPACE_ENV_PREFIX)
    assert len(statements) == 1

    sql = _normalize_sql(statements[0])
    assert "UPDATE service_instances AS instance" in sql
    assert "instance.config::jsonb" in sql
    assert "jsonb_each(" in sql
    assert "jsonb_object_agg(" in sql
    assert "jsonb_typeof(instance.config::jsonb -> 'environment') = 'object'" in sql
    assert "CHAR_LENGTH('NINECLAW_WORKSPACE_')" in sql
    assert "NINECLAW_WORKSPACE_'" in sql
    assert "NINECLAW_MANAGER_URL" in sql
    assert ")::json WHERE" in sql


def test_workspace_environment_migration_downgrade_does_not_restore_secrets(
    monkeypatch,
):
    migration = _migration_module()
    statements: list[object] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    assert statements == []

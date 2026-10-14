"""Regression checks for the immutable node-type catalog migration snapshot."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from jsonschema import Draft202012Validator
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.services.workflow.node_types import node_type_ids


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260723_000001_023_update_workflow_node_type_definitions_v2.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "workflow_node_type_catalog_023", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_node_type_catalog_migration_seeds_complete_editor_metadata():
    migration = _migration_module()
    items = migration._NODE_TYPE_DEFINITIONS

    assert [item["type"] for item in items] == [
        "start",
        "end",
        "hermes_agent",
        "condition",
        "loop",
    ]
    assert {item["type"] for item in items} == node_type_ids()
    required = {
        "type",
        "name",
        "description",
        "category",
        "type_version",
        "executor_version",
        "input_ports",
        "output_ports",
        "config_schema",
        "default_config",
        "capabilities",
    }
    assert all(required <= set(item) for item in items)
    for item in items:
        assert isinstance(item["config_schema"]["additionalProperties"], bool)
        Draft202012Validator.check_schema(item["config_schema"])

    condition = items[3]
    assert condition["output_ports"][0]["source"] == "config.ports[]"
    loop = items[4]
    assert loop["capabilities"]["container"] is True
    assert loop["capabilities"]["nested_loop"] is False


def test_node_type_catalog_migration_escapes_json_colons_before_sqlalchemy_parsing(
    monkeypatch,
):
    migration = _migration_module()
    statements: list[object] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert len(statements) == len(migration._NODE_TYPE_DEFINITIONS)
    for statement in statements:
        assert r"\:" in str(statement)
        compiled = sa.text(str(statement)).compile(dialect=postgresql.dialect())
        assert compiled.params == {}
        assert r"\:" not in str(compiled)

"""Regression checks for recoverable workflow Artifact GC migration 018."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import sqlalchemy as sa


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION_PATH = (
    _PROJECT_ROOT
    / "alembic/versions/20260721_000005_add_workflow_artifact_gc_indexes.py"
)
_ENV_PATH = _PROJECT_ROOT / "alembic/env.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "workflow_artifact_gc_indexes_018", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, *, row=None, scalar=None) -> None:
        self._row = row
        self._scalar = scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar


class _Bind:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, *, offset_default="0", index_rows=None) -> None:
        self.offset_default = offset_default
        self.index_rows = index_rows or {}
        self.executed: list[tuple[str, dict | None]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "pg_attrdef" in sql:
            return _Result(scalar=self.offset_default)
        return _Result(row=self.index_rows.get(params["index_name"]))


class _Inspector:
    def __init__(self, *, exists=True, columns=None, primary_key=None) -> None:
        self.exists = exists
        self.columns = columns or _valid_columns()
        self.primary_key = primary_key or ["cursor_key"]

    def has_table(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return self.exists

    def get_columns(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return self.columns

    def get_pk_constraint(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return {"constrained_columns": self.primary_key}

    def get_foreign_keys(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return []

    def get_unique_constraints(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return []

    def get_check_constraints(self, table_name):
        assert table_name == "workflow_artifact_gc_cursors"
        return []


class _AutocommitBlock:
    def __init__(self, owner) -> None:
        self.owner = owner

    def __enter__(self):
        self.owner.entries += 1

    def __exit__(self, exc_type, exc, traceback):
        return False


class _MigrationContext:
    def __init__(self) -> None:
        self.entries = 0

    def autocommit_block(self):
        return _AutocommitBlock(self)


def _valid_columns():
    return [
        {
            "name": "cursor_key",
            "type": sa.VARCHAR(length=128),
            "nullable": False,
            "default": None,
        },
        {
            "name": "offset",
            "type": sa.INTEGER(),
            "nullable": False,
            "default": "0",
        },
        {
            "name": "updated_at",
            "type": sa.TIMESTAMP(timezone=False),
            "nullable": False,
            "default": None,
        },
    ]


def _index_state(migration, spec, **overrides):
    values = {
        "table_name": spec.table_name,
        "columns": spec.columns,
        "access_method": "btree",
        "unique": False,
        "has_predicate": False,
        "has_expressions": False,
        "has_included_columns": False,
        "is_valid": True,
        "is_ready": True,
        "is_live": True,
    }
    values.update(overrides)
    return migration._IndexState(**values)


def test_existing_cursor_table_is_reused_only_after_contract_validation(monkeypatch):
    migration = _migration_module()
    bind = _Bind()
    monkeypatch.setattr(migration.sa, "inspect", lambda _: _Inspector())
    created: list[str] = []
    monkeypatch.setattr(migration, "_create_cursor_table", lambda: created.append("x"))

    migration._ensure_cursor_table_contract(bind)

    assert created == []
    assert len(bind.executed) == 1


def test_cursor_table_contract_rejects_wrong_offset_default(monkeypatch):
    migration = _migration_module()
    monkeypatch.setattr(migration.sa, "inspect", lambda _: _Inspector())

    with pytest.raises(RuntimeError, match="offset must have server default 0"):
        migration._validate_cursor_table_contract(_Bind(offset_default=None))


def test_cursor_table_contract_rejects_unexpected_columns(monkeypatch):
    migration = _migration_module()
    columns = _valid_columns() + [
        {
            "name": "unexpected",
            "type": sa.INTEGER(),
            "nullable": True,
            "default": None,
        }
    ]
    monkeypatch.setattr(migration.sa, "inspect", lambda _: _Inspector(columns=columns))

    with pytest.raises(RuntimeError, match="unexpected columns: unexpected"):
        migration._validate_cursor_table_contract(_Bind())


def test_upgrade_skips_valid_indexes_and_rebuilds_invalid_expected_index(monkeypatch):
    migration = _migration_module()
    context = _MigrationContext()
    bind = _Bind()
    first, second = migration._INDEXES
    states = {
        first.name: _index_state(migration, first),
        second.name: _index_state(migration, second, is_valid=False, is_ready=False),
    }
    operations: list[tuple[str, str]] = []
    monkeypatch.setattr(migration, "_is_offline_mode", lambda: False)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(migration, "_ensure_cursor_table_contract", lambda _: None)
    monkeypatch.setattr(
        migration, "_read_index_state", lambda _, spec: states[spec.name]
    )
    monkeypatch.setattr(
        migration, "_drop_index", lambda spec: operations.append(("drop", spec.name))
    )
    monkeypatch.setattr(
        migration,
        "_create_index",
        lambda spec: operations.append(("create", spec.name)),
    )

    migration.upgrade()

    assert context.entries == 1
    assert operations == [("drop", second.name), ("create", second.name)]


def test_upgrade_creates_missing_index_and_refuses_wrong_named_index(monkeypatch):
    migration = _migration_module()
    context = _MigrationContext()
    bind = _Bind()
    first, second = migration._INDEXES
    states = {
        first.name: None,
        second.name: _index_state(migration, second, columns=("created_at", "status")),
    }
    operations: list[tuple[str, str]] = []
    monkeypatch.setattr(migration, "_is_offline_mode", lambda: False)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(migration, "_ensure_cursor_table_contract", lambda _: None)
    monkeypatch.setattr(
        migration, "_read_index_state", lambda _, spec: states[spec.name]
    )
    monkeypatch.setattr(
        migration,
        "_create_index",
        lambda spec: operations.append(("create", spec.name)),
    )
    monkeypatch.setattr(
        migration, "_drop_index", lambda spec: operations.append(("drop", spec.name))
    )

    with pytest.raises(RuntimeError, match=second.name):
        migration.upgrade()

    assert operations == []


def test_offline_upgrade_does_not_request_a_database_bind(monkeypatch):
    migration = _migration_module()
    context = _MigrationContext()
    operations: list[tuple[str, str | None]] = []
    monkeypatch.setattr(migration, "_is_offline_mode", lambda: True)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: pytest.fail("offline migration must not request a bind"),
    )
    monkeypatch.setattr(
        migration, "_create_cursor_table", lambda: operations.append(("table", None))
    )
    monkeypatch.setattr(
        migration,
        "_create_index",
        lambda spec: operations.append(("index", spec.name)),
    )

    migration.upgrade()

    assert context.entries == 1
    assert operations == [
        ("table", None),
        ("index", "ix_workflow_artifacts_uri"),
        ("index", "ix_workflow_artifacts_status_created_at"),
    ]


def test_index_catalog_state_preserves_validity_and_definition_fields():
    migration = _migration_module()
    spec = migration._INDEXES[0]
    row = {
        "table_name": spec.table_name,
        "key_columns": list(spec.columns),
        "access_method": "btree",
        "is_unique": False,
        "has_predicate": False,
        "has_expressions": False,
        "has_included_columns": False,
        "is_valid": False,
        "is_ready": True,
        "is_live": True,
    }

    state = migration._read_index_state(_Bind(index_rows={spec.name: row}), spec)

    assert state is not None
    assert state.matches(spec)
    assert state.is_usable is False
    assert "pg_table_is_visible(index_relation.oid)" in str(migration._INDEX_STATE_SQL)


def test_downgrade_validates_cursor_table_before_dropping_indexes(monkeypatch):
    migration = _migration_module()
    context = _MigrationContext()
    bind = _Bind()
    operations: list[tuple[str, str]] = []
    monkeypatch.setattr(migration, "_is_offline_mode", lambda: False)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(migration.sa, "inspect", lambda _: _Inspector())
    monkeypatch.setattr(
        migration,
        "_validate_cursor_table_contract",
        lambda _: (_ for _ in ()).throw(RuntimeError("bad cursor table")),
    )
    monkeypatch.setattr(
        migration, "_drop_index", lambda spec: operations.append(("drop", spec.name))
    )

    with pytest.raises(RuntimeError, match="bad cursor table"):
        migration.downgrade()

    assert context.entries == 0
    assert operations == []


def test_alembic_environment_uses_session_lock_and_per_migration_transactions():
    source = _ENV_PATH.read_text()

    assert "pg_advisory_lock" in source
    assert "pg_advisory_unlock" in source
    assert "Alembic migrations require a fresh database connection" in source
    assert source.count("transaction_per_migration=True") == 2

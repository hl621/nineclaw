"""Add durable cursors and indexes for workflow Artifact garbage collection.

Revision ID: 018
Revises: 017
Create Date: 2026-07-21 00:05:00.000000
"""

from dataclasses import dataclass
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CURSOR_TABLE = "workflow_artifact_gc_cursors"
_ARTIFACT_TABLE = "workflow_artifacts"


@dataclass(frozen=True)
class _IndexSpec:
    name: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class _IndexState:
    table_name: str
    columns: tuple[str | None, ...]
    access_method: str
    unique: bool
    has_predicate: bool
    has_expressions: bool
    has_included_columns: bool
    is_valid: bool
    is_ready: bool
    is_live: bool

    def matches(self, spec: _IndexSpec) -> bool:
        return (
            self.table_name == spec.table_name
            and self.columns == spec.columns
            and self.access_method == "btree"
            and not self.unique
            and not self.has_predicate
            and not self.has_expressions
            and not self.has_included_columns
        )

    @property
    def is_usable(self) -> bool:
        return self.is_valid and self.is_ready and self.is_live


_INDEXES = (
    _IndexSpec(
        name="ix_workflow_artifacts_uri",
        table_name=_ARTIFACT_TABLE,
        columns=("uri",),
    ),
    _IndexSpec(
        name="ix_workflow_artifacts_status_created_at",
        table_name=_ARTIFACT_TABLE,
        columns=("status", "created_at"),
    ),
)

_OFFSET_DEFAULT_SQL = sa.text(
    """
    SELECT pg_get_expr(default_value.adbin, default_value.adrelid)
    FROM pg_attrdef AS default_value
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = default_value.adrelid
     AND attribute.attnum = default_value.adnum
    JOIN pg_class AS table_relation
      ON table_relation.oid = attribute.attrelid
    WHERE table_relation.relname = :table_name
      AND attribute.attname = 'offset'
      AND pg_table_is_visible(table_relation.oid)
    """
)

_INDEX_STATE_SQL = sa.text(
    """
    SELECT
        table_relation.relname AS table_name,
        index_definition.indisvalid AS is_valid,
        index_definition.indisready AS is_ready,
        index_definition.indislive AS is_live,
        index_definition.indisunique AS is_unique,
        access_method.amname AS access_method,
        index_definition.indnatts > index_definition.indnkeyatts
            AS has_included_columns,
        pg_get_expr(index_definition.indpred, index_definition.indrelid)
            IS NOT NULL AS has_predicate,
        pg_get_expr(index_definition.indexprs, index_definition.indrelid)
            IS NOT NULL AS has_expressions,
        ARRAY(
            SELECT attribute.attname
            FROM unnest(index_definition.indkey)
                WITH ORDINALITY AS key_column(attnum, ordinality)
            LEFT JOIN pg_attribute AS attribute
              ON attribute.attrelid = index_definition.indrelid
             AND attribute.attnum = key_column.attnum
            WHERE key_column.ordinality <= index_definition.indnkeyatts
            ORDER BY key_column.ordinality
        ) AS key_columns
    FROM pg_index AS index_definition
    JOIN pg_class AS index_relation
      ON index_relation.oid = index_definition.indexrelid
    JOIN pg_class AS table_relation
      ON table_relation.oid = index_definition.indrelid
    JOIN pg_am AS access_method
      ON access_method.oid = index_relation.relam
    WHERE index_relation.relname = :index_name
      AND pg_table_is_visible(index_relation.oid)
    """
)


def _is_offline_mode() -> bool:
    return context.is_offline_mode()


def _create_cursor_table() -> None:
    op.create_table(
        _CURSOR_TABLE,
        sa.Column("cursor_key", sa.String(length=128), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("cursor_key"),
    )


def _require_postgresql(bind) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError("revision 018 requires a PostgreSQL database")


def _zero_integer_default(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.replace(" ", "").replace("(", "").replace(")", "")
    return normalized in {"0", "0::integer", "0::int4"}


def _validate_cursor_table_contract(bind) -> None:
    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column for column in inspector.get_columns(_CURSOR_TABLE)
    }
    errors: list[str] = []
    expected_columns = {"cursor_key", "offset", "updated_at"}
    unexpected_columns = sorted(set(columns).difference(expected_columns))
    if unexpected_columns:
        errors.append("unexpected columns: " + ", ".join(unexpected_columns))

    cursor_key = columns.get("cursor_key")
    if cursor_key is None:
        errors.append("missing cursor_key")
    elif not isinstance(cursor_key["type"], sa.String) or (
        cursor_key["type"].length != 128
    ):
        errors.append("cursor_key must be VARCHAR(128)")
    elif cursor_key.get("nullable") is not False:
        errors.append("cursor_key must be NOT NULL")
    elif cursor_key.get("default") is not None:
        errors.append("cursor_key must not have a server default")

    offset = columns.get("offset")
    if offset is None:
        errors.append("missing offset")
    elif not isinstance(offset["type"], sa.Integer):
        errors.append("offset must be INTEGER")
    elif offset.get("nullable") is not False:
        errors.append("offset must be NOT NULL")
    elif not _zero_integer_default(
        bind.execute(
            _OFFSET_DEFAULT_SQL, {"table_name": _CURSOR_TABLE}
        ).scalar_one_or_none()
    ):
        errors.append("offset must have server default 0")

    updated_at = columns.get("updated_at")
    if updated_at is None:
        errors.append("missing updated_at")
    elif not isinstance(updated_at["type"], sa.DateTime) or getattr(
        updated_at["type"], "timezone", False
    ):
        errors.append("updated_at must be TIMESTAMP WITHOUT TIME ZONE")
    elif updated_at.get("nullable") is not False:
        errors.append("updated_at must be NOT NULL")
    elif updated_at.get("default") is not None:
        errors.append("updated_at must not have a server default")

    primary_key = inspector.get_pk_constraint(_CURSOR_TABLE).get("constrained_columns")
    if primary_key != ["cursor_key"]:
        errors.append("primary key must be cursor_key")
    if inspector.get_foreign_keys(_CURSOR_TABLE):
        errors.append("table must not have foreign keys")
    if inspector.get_unique_constraints(_CURSOR_TABLE):
        errors.append("table must not have unique constraints")
    if inspector.get_check_constraints(_CURSOR_TABLE):
        errors.append("table must not have check constraints")

    if errors:
        raise RuntimeError(
            f"{_CURSOR_TABLE} does not match revision 018: " + "; ".join(errors)
        )


def _ensure_cursor_table_contract(bind) -> None:
    if not sa.inspect(bind).has_table(_CURSOR_TABLE):
        _create_cursor_table()
        return
    _validate_cursor_table_contract(bind)


def _read_index_state(bind, spec: _IndexSpec) -> _IndexState | None:
    row = (
        bind.execute(_INDEX_STATE_SQL, {"index_name": spec.name})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _IndexState(
        table_name=row["table_name"],
        columns=tuple(row["key_columns"] or ()),
        access_method=row["access_method"],
        unique=bool(row["is_unique"]),
        has_predicate=bool(row["has_predicate"]),
        has_expressions=bool(row["has_expressions"]),
        has_included_columns=bool(row["has_included_columns"]),
        is_valid=bool(row["is_valid"]),
        is_ready=bool(row["is_ready"]),
        is_live=bool(row["is_live"]),
    )


def _create_index(spec: _IndexSpec) -> None:
    op.create_index(
        spec.name,
        spec.table_name,
        list(spec.columns),
        postgresql_concurrently=True,
    )


def _drop_index(spec: _IndexSpec) -> None:
    op.drop_index(
        spec.name,
        table_name=spec.table_name,
        postgresql_concurrently=True,
    )


def _index_recovery_plan(bind) -> tuple[tuple[_IndexSpec, bool], ...]:
    plan: list[tuple[_IndexSpec, bool]] = []
    for spec in _INDEXES:
        state = _read_index_state(bind, spec)
        if state is None:
            plan.append((spec, False))
            continue
        if not state.matches(spec):
            raise RuntimeError(
                f"{spec.name} does not match revision 018: expected "
                f"{spec.table_name}({', '.join(spec.columns)}) btree non-unique index"
            )
        if not state.is_usable:
            plan.append((spec, True))
    return tuple(plan)


def _apply_index_recovery_plan(plan: tuple[tuple[_IndexSpec, bool], ...]) -> None:
    for spec, rebuild in plan:
        if rebuild:
            _drop_index(spec)
        _create_index(spec)


def _index_drop_plan(bind) -> tuple[_IndexSpec, ...]:
    plan: list[_IndexSpec] = []
    for spec in reversed(_INDEXES):
        state = _read_index_state(bind, spec)
        if state is None:
            continue
        if not state.matches(spec):
            raise RuntimeError(
                f"{spec.name} does not match revision 018 and will not be dropped"
            )
        plan.append(spec)
    return tuple(plan)


def upgrade() -> None:
    if _is_offline_mode():
        _create_cursor_table()
        with op.get_context().autocommit_block():
            for spec in _INDEXES:
                _create_index(spec)
        return

    bind = op.get_bind()
    _require_postgresql(bind)
    _ensure_cursor_table_contract(bind)
    index_recovery_plan = _index_recovery_plan(bind)
    with op.get_context().autocommit_block():
        _apply_index_recovery_plan(index_recovery_plan)


def downgrade() -> None:
    if _is_offline_mode():
        with op.get_context().autocommit_block():
            for spec in reversed(_INDEXES):
                _drop_index(spec)
        op.drop_table(_CURSOR_TABLE)
        return

    bind = op.get_bind()
    _require_postgresql(bind)
    cursor_table_exists = sa.inspect(bind).has_table(_CURSOR_TABLE)
    if cursor_table_exists:
        _validate_cursor_table_contract(bind)
    index_drop_plan = _index_drop_plan(bind)
    with op.get_context().autocommit_block():
        for spec in index_drop_plan:
            _drop_index(spec)
    if cursor_table_exists:
        op.drop_table(_CURSOR_TABLE)

"""Add workflow dataflow state structures.

Revision ID: 022
Revises: 021
Create Date: 2026-07-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_artifacts",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "workflow_node_runs",
        sa.Column(
            "variable_state",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "workflow_variable_writes",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "scope_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_scope_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "node_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_attempts.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="staged",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id", "name", name="uq_workflow_variable_write_attempt_name"
        ),
    )
    op.create_index(
        "ix_workflow_variable_writes_tenant_id",
        "workflow_variable_writes",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_variable_writes_run_scope_node_status",
        "workflow_variable_writes",
        ["workflow_run_id", "scope_run_id", "node_run_id", "status"],
    )
    op.create_index(
        "ix_workflow_variable_writes_attempt_status",
        "workflow_variable_writes",
        ["attempt_id", "status"],
    )

    op.create_table(
        "workflow_control_decisions",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "scope_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_scope_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_attempts.id"),
            nullable=False,
        ),
        sa.Column(
            "target_node_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_runs.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column(
            "allowed_ports",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("value", JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "target_node_run_id",
            "kind",
            name="uq_workflow_control_decision_target",
        ),
        sa.UniqueConstraint("token", name="uq_workflow_control_decision_token"),
    )
    op.create_index(
        "ix_workflow_control_decisions_tenant_id",
        "workflow_control_decisions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_control_decisions_attempt_status",
        "workflow_control_decisions",
        ["attempt_id", "status"],
    )
    op.create_index(
        "ix_workflow_control_decisions_target_status",
        "workflow_control_decisions",
        ["target_node_run_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("workflow_control_decisions")
    op.drop_table("workflow_variable_writes")
    op.drop_column("workflow_node_runs", "variable_state")
    op.drop_column("workflow_artifacts", "kind")

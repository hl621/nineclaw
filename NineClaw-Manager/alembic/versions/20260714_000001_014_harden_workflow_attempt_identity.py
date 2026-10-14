"""Bind external Hermes Run identities to one executor instance and Attempt.

Revision ID: 014
Revises: 013
Create Date: 2026-07-14 00:01:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_node_attempts",
        sa.Column("executor_instance_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_workflow_node_attempts_executor_instance_id",
        "workflow_node_attempts",
        ["executor_instance_id"],
    )
    op.create_unique_constraint(
        "uq_workflow_attempt_external_run",
        "workflow_node_attempts",
        ["tenant_id", "executor_instance_id", "external_run_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_attempt_external_run",
        "workflow_node_attempts",
        type_="unique",
    )
    op.drop_index(
        "ix_workflow_node_attempts_executor_instance_id",
        table_name="workflow_node_attempts",
    )
    op.drop_column("workflow_node_attempts", "executor_instance_id")

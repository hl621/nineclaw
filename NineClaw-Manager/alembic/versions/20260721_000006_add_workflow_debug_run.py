"""Add workflow node-debug run metadata.

Revision ID: 019
Revises: 018
Create Date: 2026-07-21 00:06:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column(
            "run_kind",
            sa.String(length=32),
            nullable=False,
            server_default="workflow",
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("debug_node_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "debug_node_id")
    op.drop_column("workflow_runs", "run_kind")

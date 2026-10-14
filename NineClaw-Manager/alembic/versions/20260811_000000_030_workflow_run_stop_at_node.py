"""Add stop_at_node_id to workflow_runs for run-until execution.

Revision ID: 030
Revises: 029
Create Date: 2026-08-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("stop_at_node_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "stop_at_node_id")

"""Add deleted_at column to workflows for logical delete.

Revision ID: 027
Revises: 026
Create Date: 2026-08-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_workflows_deleted_at", "workflows", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_workflows_deleted_at", table_name="workflows")
    op.drop_column("workflows", "deleted_at")


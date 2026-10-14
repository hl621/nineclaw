"""Add durable workflow Artifact Attempt provenance.

Revision ID: 016
Revises: 015
Create Date: 2026-07-21 00:03:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_artifacts",
        sa.Column(
            "created_by_attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_attempts.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workflow_artifacts_created_by_attempt_id",
        "workflow_artifacts",
        ["created_by_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_artifacts_created_by_attempt_id",
        table_name="workflow_artifacts",
    )
    op.drop_column("workflow_artifacts", "created_by_attempt_id")

"""Make workflow_node_conversations.workflow_version_id nullable for draft conversations.

Revision ID: 029
Revises: 028
Create Date: 2026-08-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "workflow_node_conversations",
        "workflow_version_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_node_conversations",
        "workflow_version_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )

"""Add external_knowledge_configs table.

Revision ID: 009
Revises: 008
Create Date: 2026-06-05 21:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_knowledge_configs",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("backend", sa.String(32), nullable=False, server_default="ragflow"),
        sa.Column("base_url", sa.String(512), nullable=False, server_default=""),
        sa.Column("api_key", sa.String(1024), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("external_knowledge_configs")

"""Add remote_docker_configs table.

Revision ID: 011
Revises: 010
Create Date: 2026-06-17 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "remote_docker_configs",
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ssh_host", sa.String(255), nullable=False, server_default=""),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("ssh_username", sa.String(255), nullable=False, server_default=""),
        sa.Column("ssh_password", sa.String(1024), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("remote_docker_configs")

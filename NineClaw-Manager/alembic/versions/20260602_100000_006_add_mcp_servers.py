"""Add mcp_servers table.

Revision ID: 006
Revises: 005
Create Date: 2026-06-02 10:00:00.000000

Creates the ``mcp_servers`` table that stores MCP (Model Context Protocol)
servers registered by each tenant. Two transport types are supported:

- ``stdio`` — local subprocess (command + args + env)
- ``url``   — remote HTTP endpoint (url + headers)

When deployed, entries are written into the ``mcp_servers`` block of a
nineclaw instance's Hermes config.yaml keyed by ``name``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "description", sa.String(1024), nullable=False, server_default=""
        ),
        sa.Column("transport", sa.String(16), nullable=False),
        # stdio fields
        sa.Column(
            "command", sa.String(512), nullable=False, server_default=""
        ),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "env",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        # url fields
        sa.Column(
            "url", sa.String(512), nullable=False, server_default=""
        ),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        # per-server overrides
        sa.Column("timeout", sa.Float(), nullable=True),
        sa.Column("connect_timeout", sa.Float(), nullable=True),
        # state
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "last_health_status",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_mcp_servers_tenant_id",
        "mcp_servers",
        ["tenant_id"],
    )
    op.create_unique_constraint(
        "uq_mcp_servers_tenant_name",
        "mcp_servers",
        ["tenant_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mcp_servers_tenant_name", "mcp_servers", type_="unique"
    )
    op.drop_index("ix_mcp_servers_tenant_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
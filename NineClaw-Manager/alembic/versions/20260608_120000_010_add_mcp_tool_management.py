"""Add MCP tool management columns to mcp_servers.

Revision ID: 010
Revises: 009
Create Date: 2026-06-08 12:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("tools", JSONB, nullable=True))
    op.add_column("mcp_servers", sa.Column("tool_settings", JSONB, nullable=True))
    op.add_column("mcp_servers", sa.Column("tools_discovered_at", sa.DateTime, nullable=True))
    op.add_column("mcp_servers", sa.Column("tools_error", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_servers", "tools_error")
    op.drop_column("mcp_servers", "tools_discovered_at")
    op.drop_column("mcp_servers", "tool_settings")
    op.drop_column("mcp_servers", "tools")

"""Add url_base to web_sources.

Revision ID: 007
Revises: 006
Create Date: 2026-06-03 01:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("web_sources", sa.Column("url_base", sa.String(2048), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("web_sources", "url_base")

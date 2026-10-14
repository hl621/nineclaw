"""Add provider health columns.

Revision ID: 005
Revises: 004
Create Date: 2026-05-27 19:15:00.000000

Adds ``last_health_status`` and ``last_checked_at`` to the ``providers``
table. The Models page renders the cached value on first load; a periodic
SSE probe refreshes both columns plus the live UI.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column(
            "last_health_status",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "providers",
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("providers", "last_checked_at")
    op.drop_column("providers", "last_health_status")

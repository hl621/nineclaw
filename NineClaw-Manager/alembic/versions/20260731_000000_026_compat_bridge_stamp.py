"""Compatibility stub for databases already stamped at revision 026.

Some deploy environments recorded alembic_version=026 while the Manager
image only shipped through 025, which makes startup fail with:

    Can't locate revision identified by '026'

This revision is intentionally empty so existing DBs at 026 can start,
and fresh installs simply no-op from 025 → 026.

Revision ID: 026
Revises: 025
Create Date: 2026-07-31 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union


revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema changes — bridge stamp only.
    pass


def downgrade() -> None:
    pass

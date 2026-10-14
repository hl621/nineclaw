"""Make workflow workspace execution IDs globally unambiguous.

Revision ID: 017
Revises: 016
Create Date: 2026-07-21 00:04:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_workflow_attempt_execution_id",
        "workflow_node_attempts",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_attempt_execution_id",
        "workflow_node_attempts",
        type_="unique",
    )

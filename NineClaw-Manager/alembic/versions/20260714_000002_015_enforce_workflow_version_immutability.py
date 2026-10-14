"""Enforce immutable published workflow versions for existing installations.

Revision ID: 015
Revises: 014
Create Date: 2026-07-14 00:02:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_workflow_version_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'workflow_versions are immutable after publication';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER workflow_versions_immutable
        BEFORE UPDATE OR DELETE ON workflow_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_workflow_version_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS workflow_versions_immutable ON workflow_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_workflow_version_mutation()")

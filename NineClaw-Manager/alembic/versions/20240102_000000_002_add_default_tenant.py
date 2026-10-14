"""Add default tenant for MVP.

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

This migration creates the default tenant required for MVP operations.
The instance service uses tenant_id='default' as the default value.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"  # Depends on initial schema
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert default tenant
    # Using raw SQL to bypass model dependencies
    op.execute(
        """
        INSERT INTO tenants (id, name, api_key_hash, allowed_commands, is_active)
        VALUES (
            'default',
            'Default Tenant',
            '',  -- Empty hash for MVP (no API key required)
            '[]'::jsonb,
            true
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove default tenant
    op.execute(
        """
        DELETE FROM tenants WHERE id = 'default'
        """
    )

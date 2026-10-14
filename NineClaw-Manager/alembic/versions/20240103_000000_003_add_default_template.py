"""Add default service template for MVP.

Revision ID: 003
Revises: 002
Create Date: 2024-01-03 00:00:00.000000

This migration creates the default service template required for MVP operations.
The instance service uses template_id='00000000-0000-0000-0000-000000000000' as placeholder.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert default service template
    op.execute(
        """
        INSERT INTO service_templates (
            id, name, image, ports, volumes, env_template, 
            resource_limits, variables, created_at, updated_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000000'::uuid,
            'Default Nineclaw Template',
            'nineclaw:latest',
            '[8642, 8643, 8644]'::jsonb,
            '[]'::jsonb,
            '{"API_SERVER_ENABLED": "true", "API_SERVER_HOST": "0.0.0.0", "API_SERVER_CORS_ORIGINS": "*"}'::jsonb,
            '{"memory": "4G", "cpu": 2.0}'::jsonb,
            '[]'::jsonb,
            now(),
            now()
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove default template
    op.execute(
        """
        DELETE FROM service_templates 
        WHERE id = '00000000-0000-0000-0000-000000000000'::uuid
        """
    )

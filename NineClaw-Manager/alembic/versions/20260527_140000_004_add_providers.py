"""Add providers table.

Revision ID: 004
Revises: 003
Create Date: 2026-05-27 14:00:00.000000

Creates the ``providers`` table that stores OpenAI-compatible LLM
providers registered by each tenant. Powers the Models page in the
NineClaw WebUI.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "providers",
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
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column(
            "api_key", sa.String(1024), nullable=False, server_default=""
        ),
        sa.Column(
            "models",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
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
        "ix_providers_tenant_id",
        "providers",
        ["tenant_id"],
    )
    op.create_unique_constraint(
        "uq_providers_tenant_name",
        "providers",
        ["tenant_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_providers_tenant_name", "providers", type_="unique"
    )
    op.drop_index("ix_providers_tenant_id", table_name="providers")
    op.drop_table("providers")

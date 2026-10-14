"""replace old columns with request_config extractor_code url_base

Revision ID: 001
Revises:
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old columns
    op.drop_column("search_sources", "base_url")
    op.drop_column("search_sources", "method")
    op.drop_column("search_sources", "headers")
    op.drop_column("search_sources", "params_template")
    op.drop_column("search_sources", "result_extract_path")

    # Add new columns
    op.add_column("search_sources", sa.Column("request_config", JSONB, nullable=True))
    op.add_column("search_sources", sa.Column("extractor_code", sa.Text, nullable=True))
    op.add_column("search_sources", sa.Column("url_base", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("search_sources", "request_config")
    op.drop_column("search_sources", "extractor_code")
    op.drop_column("search_sources", "url_base")

    op.add_column("search_sources", sa.Column("base_url", sa.String(512), nullable=False, server_default=""))
    op.add_column("search_sources", sa.Column("method", sa.String(8), nullable=False, server_default="GET"))
    op.add_column("search_sources", sa.Column("headers", JSONB, nullable=True))
    op.add_column("search_sources", sa.Column("params_template", JSONB, nullable=True))
    op.add_column("search_sources", sa.Column("result_extract_path", sa.String(256), nullable=True))

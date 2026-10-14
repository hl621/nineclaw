"""Add tenant+name unique constraints to service_instances and web_sources.

Revision ID: 012
Revises: 011
Create Date: 2026-07-01 00:00:00.000000

Introduces a per-tenant uniqueness constraint on the human-readable name
of nineclaw service instances and web sources. Duplicate rows are renamed
in-place (suffix `` (2)``, `` (3)``, …) before the constraint is added.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEDUP_SERVICE_INSTANCES = text(
    """
    UPDATE service_instances AS si
    SET name = LEFT(si.name, 240) || ' (' || d.rn::text || ')'
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY tenant_id, name
                   ORDER BY created_at ASC, id ASC
               ) AS rn
        FROM service_instances
    ) AS d
    WHERE si.id = d.id
      AND d.rn > 1
    """
)

_DEDUP_WEB_SOURCES = text(
    """
    UPDATE web_sources AS ws
    SET name = LEFT(ws.name, 120) || ' (' || d.rn::text || ')'
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY tenant_id, name
                   ORDER BY created_at ASC, id ASC
               ) AS rn
        FROM web_sources
    ) AS d
    WHERE ws.id = d.id
      AND d.rn > 1
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(_DEDUP_SERVICE_INSTANCES)
    bind.execute(_DEDUP_WEB_SOURCES)
    op.create_unique_constraint(
        "uq_service_instances_tenant_name",
        "service_instances",
        ["tenant_id", "name"],
    )
    op.create_unique_constraint(
        "uq_web_sources_tenant_name",
        "web_sources",
        ["tenant_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_web_sources_tenant_name", "web_sources", type_="unique")
    op.drop_constraint(
        "uq_service_instances_tenant_name", "service_instances", type_="unique"
    )

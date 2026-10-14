"""Remove persisted Workspace runtime environment values.

Revision ID: 025
Revises: 024
Create Date: 2026-07-23 00:03:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WORKSPACE_ENV_PREFIX = "NINECLAW_WORKSPACE_"

_REMOVE_PERSISTED_WORKSPACE_ENVIRONMENT = text(
    """
    UPDATE service_instances AS instance
    SET config = jsonb_set(
        instance.config::jsonb,
        '{environment}',
        COALESCE(
            (
                SELECT jsonb_object_agg(env.environment_key, env.environment_value)
                FROM jsonb_each(
                    CASE
                        WHEN jsonb_typeof(
                            instance.config::jsonb -> 'environment'
                        ) = 'object'
                        THEN instance.config::jsonb -> 'environment'
                        ELSE '{}'::jsonb
                    END
                ) AS env(environment_key, environment_value)
                WHERE LEFT(
                    env.environment_key,
                    CHAR_LENGTH('NINECLAW_WORKSPACE_')
                ) <> 'NINECLAW_WORKSPACE_'
                  AND env.environment_key <> 'NINECLAW_MANAGER_URL'
            ),
            '{}'::jsonb
        ),
        true
    )::json
    WHERE jsonb_typeof(instance.config::jsonb) = 'object'
      AND jsonb_typeof(instance.config::jsonb -> 'environment') = 'object'
      AND EXISTS (
          SELECT 1
          FROM jsonb_object_keys(
              instance.config::jsonb -> 'environment'
          ) AS existing_environment(environment_key)
          WHERE LEFT(
              existing_environment.environment_key,
              CHAR_LENGTH('NINECLAW_WORKSPACE_')
          ) = 'NINECLAW_WORKSPACE_'
             OR existing_environment.environment_key = 'NINECLAW_MANAGER_URL'
      )
    """
)


def upgrade() -> None:
    op.execute(_REMOVE_PERSISTED_WORKSPACE_ENVIRONMENT)


def downgrade() -> None:
    # Removed environment values can contain bridge credentials. Downgrade
    # intentionally does not recreate data that has been securely discarded.
    pass

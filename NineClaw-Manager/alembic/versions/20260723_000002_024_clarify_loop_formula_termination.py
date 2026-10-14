"""Clarify DSL v2 Formula Loop termination metadata.

Revision ID: 024
Revises: 023
Create Date: 2026-07-23 00:02:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op


revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    description = json.dumps(
        "父图原子复合节点。Body 为纯 DAG 且必须只有一个 End；每轮继承上游与前轮 Artifact、变量快照。"
        "formula termination 表达式为 true 时终止循环。",
        ensure_ascii=True,
    )
    op.execute(
        "UPDATE workflow_node_type_definitions "
        "SET definition = jsonb_set("
        "jsonb_set(definition, '{description}', "
        f"'{description}'::jsonb, true), "
        "'{executor_version}', '3'::jsonb, true) "
        "WHERE type = 'loop'"
    )


def downgrade() -> None:
    # DSL v2 is a one-way product cutover; metadata is not reverted to an
    # ambiguous control-flow contract.
    pass

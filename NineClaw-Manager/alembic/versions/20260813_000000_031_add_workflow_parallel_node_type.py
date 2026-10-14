"""Add the first-class parallel node type to the editor catalog.

Revision ID: 031
Revises: 030
Create Date: 2026-08-13 00:00:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op


revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PARALLEL_DEFINITION = {
    "type": "parallel",
    "name": "并行",
    "description": (
        "父图原子复合节点。启动时并发运行全部 branch body（各自为纯 DAG 且必须只有一个 End），"
        "全部分支终态后节点才终态；输出为 {branches: {分支名: 分支 End 输出}}。"
        "on_branch_failure=continue 时全部跑完，fail_fast 时首个分支失败即请求取消其余分支。"
    ),
    "category": "control",
    "type_version": 1,
    "executor_version": 1,
    "input_ports": [
        {
            "id": "default",
            "name": "默认输入",
            "description": "作为各分支 Body 可见的 Workspace 快照。",
            "dynamic": False,
        }
    ],
    "output_ports": [
        {
            "id": "default",
            "name": "默认输出",
            "description": "聚合输出 branches 映射；全部成功分支的产物可被下游读取。",
            "dynamic": False,
        }
    ],
    "config_schema": {
        "type": "object",
        "properties": {
            "branches": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "body": {"type": "object", "description": "DSL v2 Body。"},
                    },
                    "required": ["name", "body"],
                    "additionalProperties": False,
                },
            },
            "on_branch_failure": {
                "enum": ["continue", "fail_fast"],
                "default": "continue",
            },
        },
        "required": ["branches"],
        "additionalProperties": False,
    },
    "default_config": {"on_branch_failure": "continue"},
    "capabilities": {
        "container": True,
        "nested_loop": False,
        "artifact_workspace": True,
        "variables": True,
        "control_decision": False,
    },
}


def _upsert_seed(type_id: str, display_order: int, definition: dict) -> None:
    """Idempotent JSONB seed; upgrade --sql remains reproducible.

    Dev databases were seeded with the parallel catalog row during P1
    development before this migration existed, so a plain INSERT collides
    with the primary key.  ON CONFLICT converges those pre-seeded rows to
    the canonical definition instead of failing.
    """

    escaped_type = type_id.replace("'", "''")
    payload = json.dumps(definition, ensure_ascii=True, separators=(",", ":"))
    # Alembic sends string SQL through SQLAlchemy's text() parser.  Escape
    # JSON structural colons so values such as :1 and :false are not
    # mistaken for bind parameters before PostgreSQL receives the statement.
    payload = payload.replace("'", "''").replace(":", r"\:")
    op.execute(
        "INSERT INTO workflow_node_type_definitions "
        "(type, display_order, definition) VALUES "
        f"('{escaped_type}', {display_order}, '{payload}'::jsonb"
        ") ON CONFLICT (type) DO UPDATE SET "
        "display_order = EXCLUDED.display_order, "
        "definition = EXCLUDED.definition"
    )


def upgrade() -> None:
    _upsert_seed("parallel", 5, _PARALLEL_DEFINITION)


def downgrade() -> None:
    # DSL v2 is a deliberate one-way product cutover.  Removing the catalog
    # row would hide a node type that published versions may already use.
    pass

"""Persist the workflow editor node-type catalog.

Revision ID: 021
Revises: 020
Create Date: 2026-07-22 00:01:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep the initial catalog snapshot inside this migration.  Importing runtime
# application metadata here would make a fresh upgrade depend on later code.
_NODE_TYPE_DEFINITIONS = (
    {
        "type": "start",
        "name": "开始",
        "description": "工作流入口，默认输出包含当前业务 Run 输入的包装对象。",
        "category": "control",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "输出包装对象；业务 Run 输入位于 input 字段。",
                "dynamic": False,
                "fixed_output_schema": {
                    "type": "object",
                    "required": ["input"],
                    "properties": {
                        "input": {
                            "type": "object",
                            "description": "业务 Run 请求的输入对象。",
                        }
                    },
                    "additionalProperties": False,
                },
            }
        ],
        "config_schema": {
            "type": "object",
            "description": "开始节点没有必填配置。",
            "additionalProperties": True,
        },
        "default_config": {},
        "capabilities": {
            "container": False,
            "nested_loop": False,
            "input_schema": "node_defined",
            "output_schema": "node_defined",
        },
    },
    {
        "type": "end",
        "name": "结束",
        "description": "工作流出口，透传输入快照；可通过 input_mapping.final_artifacts 声明最终产物。",
        "category": "control",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "接收直接上游节点输出。",
                "dynamic": False,
            }
        ],
        "output_ports": [],
        "config_schema": {
            "type": "object",
            "description": "结束节点没有必填配置；最终产物在 input_mapping.final_artifacts 中声明。",
            "additionalProperties": True,
        },
        "default_config": {},
        "capabilities": {
            "container": False,
            "nested_loop": False,
            "input_schema": "node_defined",
            "output_schema": "node_defined",
        },
    },
    {
        "type": "hermes_agent",
        "name": "Hermes 智能体",
        "description": "通过 Manager 异步调用一个 Hermes Agent；远端动态输出可附加当前 Attempt 的 Artifact 元数据。",
        "category": "agent",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "作为提示词模板和消息构造的节点输入快照。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "Hermes 返回的动态对象；可包含 artifacts 字段。",
                "dynamic": False,
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "当前租户的 Hermes 实例 ID。",
                },
                "prompt": {"type": "string", "description": "单条提示词。"},
                "messages": {"type": "array", "description": "消息数组。"},
                "model": {"type": "string", "description": "可选模型标识。"},
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["instance_id"],
            "anyOf": [{"required": ["prompt"]}, {"required": ["messages"]}],
            "additionalProperties": True,
        },
        "default_config": {},
        "capabilities": {
            "container": False,
            "nested_loop": False,
            "input_schema": "node_defined",
            "output_schema": "node_defined",
        },
    },
    {
        "type": "condition",
        "name": "条件分支",
        "description": "按有序条件选择第一个命中分支，否则选择唯一默认分支。",
        "category": "control",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "为分支表达式提供运行时上下文。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "branch",
                "name": "条件分支",
                "description": "每个实际输出端口由一个 branches 条目的 port 生成。",
                "dynamic": True,
                "source": "config.branches[].port",
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "branches": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "port": {"type": "string", "minLength": 1},
                            "default": {"type": "boolean"},
                            "when": {
                                "description": "受限 JSON AST 表达式。",
                            },
                        },
                        "required": ["port"],
                        "additionalProperties": True,
                    },
                }
            },
            "required": ["branches"],
            "additionalProperties": True,
        },
        "default_config": {},
        "capabilities": {
            "container": False,
            "nested_loop": False,
            "input_schema": "node_defined",
            "output_schema": "node_defined",
        },
    },
    {
        "type": "loop",
        "name": "状态循环",
        "description": "父图中的原子复合节点；Body 是至少执行一次的独立纯 DAG。",
        "category": "control",
        "type_version": 1,
        "executor_version": 1,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "传入循环的静态输入与初始状态上下文。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "包含最终状态、结果和聚合 artifacts 的循环输出。",
                "dynamic": False,
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "const": "stateful",
                    "default": "stateful",
                    "description": "首期只支持 stateful。",
                },
                "body": {"type": "object", "description": "独立工作流 DSL。"},
                "termination": {
                    "type": "object",
                    "properties": {
                        "continue_when": {
                            "description": "受限 JSON AST 表达式。",
                        }
                    },
                    "required": ["continue_when"],
                    "additionalProperties": True,
                },
                "limits": {
                    "type": "object",
                    "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
                    "required": ["max_iterations"],
                    "additionalProperties": True,
                },
                "inputs": {
                    "type": "object",
                    "properties": {"initial_state": {"type": "object"}},
                    "additionalProperties": True,
                },
            },
            "required": ["body", "termination", "limits"],
            "additionalProperties": True,
        },
        "default_config": {"mode": "stateful"},
        "capabilities": {
            "container": True,
            "nested_loop": False,
            "input_schema": "node_defined",
            "output_schema": "node_defined",
        },
    },
)


def _insert_seed(type_id: str, display_order: int, definition: dict) -> None:
    """Insert JSONB using literal SQL so ``upgrade --sql`` remains reproducible."""

    escaped_type = type_id.replace("'", "''")
    payload = json.dumps(definition, ensure_ascii=True, separators=(",", ":"))
    escaped_payload = payload.replace("'", "''").replace(":", r"\:")
    op.execute(
        "INSERT INTO workflow_node_type_definitions "
        "(type, display_order, definition) VALUES "
        f"('{escaped_type}', {display_order}, '{escaped_payload}'::jsonb"
        ")"
    )


def upgrade() -> None:
    op.create_table(
        "workflow_node_type_definitions",
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("type"),
        sa.UniqueConstraint(
            "display_order", name="uq_workflow_node_type_definitions_display_order"
        ),
    )
    for display_order, definition in enumerate(_NODE_TYPE_DEFINITIONS):
        _insert_seed(str(definition["type"]), display_order, definition)


def downgrade() -> None:
    op.drop_table("workflow_node_type_definitions")

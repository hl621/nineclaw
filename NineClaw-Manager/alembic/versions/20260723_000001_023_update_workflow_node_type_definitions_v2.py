"""Replace workflow editor catalog metadata with the DSL v2 contract.

Revision ID: 023
Revises: 022
Create Date: 2026-07-23 00:01:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op


revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAPABILITIES = {
    "container": False,
    "nested_loop": False,
    "artifact_workspace": True,
    "variables": True,
    "control_decision": False,
}

_NODE_TYPE_DEFINITIONS = (
    {
        "type": "start",
        "name": "开始",
        "description": "工作流入口。Run 输入被 Manager 物化为 workflow-input.json。",
        "category": "control",
        "type_version": 1,
        "executor_version": 2,
        "input_ports": [],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "启动后允许下游读取 workflow-input.json。",
                "dynamic": False,
            }
        ],
        "config_schema": {
            "type": "object",
            "additionalProperties": False,
        },
        "default_config": {},
        "capabilities": dict(_CAPABILITIES),
    },
    {
        "type": "end",
        "name": "结束",
        "description": "工作流出口。Manager 自动汇集已选上游闭包的非系统 Artifact。",
        "category": "control",
        "type_version": 1,
        "executor_version": 2,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "接收已选上游路径。",
                "dynamic": False,
            }
        ],
        "output_ports": [],
        "config_schema": {
            "type": "object",
            "additionalProperties": False,
        },
        "default_config": {},
        "capabilities": dict(_CAPABILITIES),
    },
    {
        "type": "hermes_agent",
        "name": "Hermes 智能体",
        "description": "Manager 调用独立 Hermes；节点通过固定 MCP 访问上游 Artifact、变量和控制工具。",
        "category": "agent",
        "type_version": 1,
        "executor_version": 2,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "触发节点；业务数据经 Artifact Workspace 获取。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "Hermes 返回被物化为 node-output.json，上传文件成为输出 Artifact。",
                "dynamic": False,
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "minLength": 1},
                "prompt": {"type": "string"},
                "messages": {"type": "array"},
                "model": {"type": "string"},
                "temperature": {"type": "number"},
                "max_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["instance_id"],
            "anyOf": [{"required": ["prompt"]}, {"required": ["messages"]}],
            "additionalProperties": True,
        },
        "default_config": {},
        "capabilities": {
            **_CAPABILITIES,
            "control_decision": True,
        },
    },
    {
        "type": "condition",
        "name": "条件分支",
        "description": "agent 模式由直接 Hermes 上游提交一次性端口；formula 模式由 Manager 受限 AST 求值。",
        "category": "control",
        "type_version": 1,
        "executor_version": 2,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "接收已选上游 Artifact 与变量快照。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "branch",
                "name": "条件分支",
                "description": "实际端口由 config.ports 定义。",
                "dynamic": True,
                "source": "config.ports[]",
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "mode": {"enum": ["agent", "formula"]},
                "ports": {
                    "type": "array",
                    "minItems": 2,
                    "items": {"type": "string", "minLength": 1},
                },
                "expression": {"description": "formula 模式的受限 JSON AST。"},
                "true_port": {"type": "string"},
                "false_port": {"type": "string"},
            },
            "required": ["mode", "ports"],
            "additionalProperties": True,
        },
        "default_config": {"mode": "formula", "ports": ["true", "false"]},
        "capabilities": {
            **_CAPABILITIES,
            "control_decision": True,
        },
    },
    {
        "type": "loop",
        "name": "循环",
        "description": "父图原子复合节点。Body 为纯 DAG 且必须只有一个 End；每轮继承上游与前轮 Artifact、变量快照。",
        "category": "control",
        "type_version": 1,
        "executor_version": 2,
        "input_ports": [
            {
                "id": "default",
                "name": "默认输入",
                "description": "作为 Body 首轮可见的 Workspace 快照。",
                "dynamic": False,
            }
        ],
        "output_ports": [
            {
                "id": "default",
                "name": "默认输出",
                "description": "循环完成后下游可读取各成功迭代产物。",
                "dynamic": False,
            }
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "body": {"type": "object", "description": "DSL v2 Body。"},
                "termination": {
                    "type": "object",
                    "properties": {
                        "mode": {"enum": ["agent", "formula"]},
                        "expression": {"description": "formula 模式受限 JSON AST。"},
                        "source_node_id": {"type": "string"},
                    },
                    "required": ["mode"],
                    "additionalProperties": True,
                },
                "limits": {
                    "type": "object",
                    "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
                    "required": ["max_iterations"],
                    "additionalProperties": False,
                },
            },
            "required": ["body", "termination", "limits"],
            "additionalProperties": False,
        },
        "default_config": {
            "termination": {"mode": "formula"},
            "limits": {"max_iterations": 1},
        },
        "capabilities": {
            **_CAPABILITIES,
            "container": True,
            "control_decision": True,
        },
    },
)


def _update_catalog(definition: dict, display_order: int) -> None:
    type_id = str(definition["type"]).replace("'", "''")
    payload = json.dumps(definition, ensure_ascii=True, separators=(",", ":"))
    # Alembic sends string SQL through SQLAlchemy's ``text()`` parser.  Escape
    # JSON structural colons so values such as ``:1`` and ``:false`` are not
    # mistaken for bind parameters before PostgreSQL receives the statement.
    payload = payload.replace("'", "''").replace(":", r"\:")
    op.execute(
        "UPDATE workflow_node_type_definitions "
        f"SET display_order = {display_order}, definition = '{payload}'::jsonb "
        f"WHERE type = '{type_id}'"
    )


def upgrade() -> None:
    for display_order, definition in enumerate(_NODE_TYPE_DEFINITIONS):
        _update_catalog(definition, display_order)


def downgrade() -> None:
    # DSL v2 is a deliberate one-way product cutover.  Restoring old catalog
    # metadata would falsely advertise unsupported v1 mapping semantics.
    pass

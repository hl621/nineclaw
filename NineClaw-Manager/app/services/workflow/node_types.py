"""Database-backed editor metadata for the fixed workflow node-type set."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowNodeTypeDefinition
from app.services.workflow.schema_validation import SchemaDefinitionError, check_schema


_SUPPORTED_NODE_TYPE_IDS: Final[frozenset[str]] = frozenset(
    {"start", "end", "hermes_agent", "condition", "loop"}
)
_REQUIRED_DEFINITION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "type",
        "name",
        "description",
        "category",
        "type_version",
        "executor_version",
        "input_ports",
        "output_ports",
        "config_schema",
        "default_config",
        "capabilities",
    }
)
_REQUIRED_CAPABILITY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "container",
        "nested_loop",
        "artifact_workspace",
        "variables",
        "control_decision",
    }
)


class NodeTypeCatalogIntegrityError(RuntimeError):
    """Raised when persisted editor metadata diverges from executable types."""


def node_type_ids() -> frozenset[str]:
    """Return type IDs accepted by the synchronous workflow compiler."""

    return _SUPPORTED_NODE_TYPE_IDS


def _is_positive_integer(value: Any) -> bool:
    return type(value) is int and value >= 1


def _is_valid_port(port: Any) -> bool:
    if not isinstance(port, dict):
        return False
    if (
        not all(
            isinstance(port.get(field), str) for field in ("id", "name", "description")
        )
        or type(port.get("dynamic")) is not bool
    ):
        return False
    source = port.get("source")
    if source is not None and not isinstance(source, str):
        return False
    fixed_output_schema = port.get("fixed_output_schema")
    if fixed_output_schema is not None and not isinstance(fixed_output_schema, dict):
        return False
    try:
        if fixed_output_schema is not None:
            check_schema(fixed_output_schema)
    except SchemaDefinitionError:
        return False
    return True


def _is_valid_definition(definition: Any, type_id: str) -> bool:
    if (
        not isinstance(definition, dict)
        or definition.get("type") != type_id
        or not _REQUIRED_DEFINITION_FIELDS <= definition.keys()
    ):
        return False
    if not all(
        isinstance(definition[field], str)
        for field in ("name", "description", "category")
    ) or not all(
        _is_positive_integer(definition[field])
        for field in ("type_version", "executor_version")
    ):
        return False
    if not isinstance(definition["input_ports"], list) or not isinstance(
        definition["output_ports"], list
    ):
        return False
    if not all(
        _is_valid_port(port)
        for port in definition["input_ports"] + definition["output_ports"]
    ):
        return False
    if (
        not isinstance(definition["config_schema"], dict)
        or not isinstance(definition["default_config"], dict)
        or not isinstance(definition["capabilities"], dict)
    ):
        return False
    capabilities = definition["capabilities"]
    if not _REQUIRED_CAPABILITY_FIELDS <= capabilities.keys() or not all(
        type(capabilities[field]) is bool for field in _REQUIRED_CAPABILITY_FIELDS
    ):
        return False
    try:
        check_schema(definition["config_schema"])
    except SchemaDefinitionError:
        return False
    return True


async def list_node_type_definitions(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Read a complete, ordered catalog without a static in-memory fallback."""

    rows = list(
        (
            await session.scalars(
                select(WorkflowNodeTypeDefinition).order_by(
                    WorkflowNodeTypeDefinition.display_order,
                    WorkflowNodeTypeDefinition.type,
                )
            )
        ).all()
    )
    row_types = [row.type for row in rows]
    if (
        len(rows) != len(_SUPPORTED_NODE_TYPE_IDS)
        or set(row_types) != _SUPPORTED_NODE_TYPE_IDS
        or len(set(row.display_order for row in rows)) != len(rows)
    ):
        raise NodeTypeCatalogIntegrityError("节点类型目录未初始化或不完整")

    definitions: list[dict[str, Any]] = []
    for row in rows:
        if not _is_valid_definition(row.definition, row.type):
            raise NodeTypeCatalogIntegrityError("节点类型目录定义损坏")
        definitions.append(deepcopy(row.definition))
    return definitions

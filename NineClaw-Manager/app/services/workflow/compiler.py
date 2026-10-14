"""Compiler and semantic validator for the version-2 workflow DSL."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.schemas.workflow import WorkflowDefinition
from app.services.workflow.expressions import ExpressionError, validate_expression
from app.services.workflow.node_types import node_type_ids


SUPPORTED_NODE_TYPES = node_type_ids()
DEFAULT_LIMITS = {
    "max_node_executions": 1000,
    "max_artifact_bytes": 1024 * 1024 * 1024,
    "max_hermes_runs": 100,
}
_VARIABLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_REMOVED_V1_NODE_FIELDS = frozenset({"input_mapping", "input_schema", "output_schema"})
_REMOVED_V1_CONFIG_FIELDS = {
    "condition": frozenset({"branches"}),
    "loop": frozenset({"mode"}),
}
_REMOVED_V1_LOOP_TERMINATION_FIELDS = frozenset({"continue_when"})


@dataclass(frozen=True)
class CompilationIssue:
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


class WorkflowCompilationError(ValueError):
    def __init__(self, issues: list[CompilationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in issues))


class UnsupportedWorkflowDslError(WorkflowCompilationError):
    """Stable rejection used by every v1 definition and execution entry point."""

    code = "WORKFLOW_DSL_V1_UNSUPPORTED"


@dataclass(frozen=True)
class CompiledWorkflow:
    definition: dict[str, Any]
    plan: dict[str, Any]
    checksum: str


def compile_workflow(
    definition: Any | WorkflowDefinition,
    *,
    nested: bool = False,
    inherited_variables: dict[str, dict[str, Any]] | None = None,
) -> CompiledWorkflow:
    """Compile one v2 DAG into a JSON-serializable execution plan.

    ``nested`` is reserved for Loop Bodies.  Loop Bodies inherit the outer
    workflow variable contract and cannot declare a second contract or nest a
    Loop.  The invariant keeps variable ownership and iteration state finite.
    """
    _ensure_v2_document(definition)
    _reject_removed_v1_fields(definition)
    try:
        model = (
            definition
            if isinstance(definition, WorkflowDefinition)
            else WorkflowDefinition.model_validate(definition)
        )
    except ValidationError as exc:
        raise WorkflowCompilationError(_pydantic_issues(exc)) from exc
    raw = model.model_dump(mode="json", exclude_none=True)
    issues: list[CompilationIssue] = []

    if model.schema_version != 2:
        # `_ensure_v2_document` handles v1 before Pydantic can erase its
        # identity.  This branch protects callers passing an already-built
        # model instance.
        raise UnsupportedWorkflowDslError(
            [
                CompilationIssue(
                    "schema_version", "不支持 DSL v1；仅支持 schema_version=2"
                )
            ]
        )

    declared_variables = raw.get("variables") or {}
    if nested and declared_variables:
        issues.append(CompilationIssue("variables", "Loop Body 不能重新声明工作流变量"))
    variables = dict(inherited_variables or {}) if nested else dict(declared_variables)
    _validate_variables(variables, issues)

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(raw["nodes"]):
        node_id = node["id"]
        if node_id in nodes_by_id:
            issues.append(
                CompilationIssue(f"nodes[{index}].id", f"节点 ID '{node_id}' 重复")
            )
            continue
        if node["type"] not in SUPPORTED_NODE_TYPES:
            issues.append(CompilationIssue(f"nodes[{index}].type", "节点类型未注册"))
        nodes_by_id[node_id] = node

    start_ids = [
        node_id for node_id, node in nodes_by_id.items() if node["type"] == "start"
    ]
    end_ids = [
        node_id for node_id, node in nodes_by_id.items() if node["type"] == "end"
    ]
    if len(start_ids) != 1:
        issues.append(CompilationIssue("nodes", "工作流必须且只能有一个 start 节点"))
    if not end_ids:
        issues.append(CompilationIssue("nodes", "工作流至少需要一个 end 节点"))

    edges_by_id: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    reverse: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    outgoing_edges: dict[str, list[dict[str, Any]]] = {
        node_id: [] for node_id in nodes_by_id
    }
    incoming_edges: dict[str, list[dict[str, Any]]] = {
        node_id: [] for node_id in nodes_by_id
    }
    for index, edge in enumerate(raw["edges"]):
        edge_id = edge["id"]
        if edge_id in edges_by_id:
            issues.append(
                CompilationIssue(f"edges[{index}].id", f"边 ID '{edge_id}' 重复")
            )
            continue
        edges_by_id[edge_id] = edge
        source = edge["source_node_id"]
        target = edge["target_node_id"]
        if source not in nodes_by_id:
            issues.append(
                CompilationIssue(
                    f"edges[{index}].source_node_id", f"节点 '{source}' 不存在"
                )
            )
            continue
        if target not in nodes_by_id:
            issues.append(
                CompilationIssue(
                    f"edges[{index}].target_node_id", f"节点 '{target}' 不存在"
                )
            )
            continue
        if source == target:
            issues.append(CompilationIssue(f"edges[{index}]", "边不能连接节点自身"))
        adjacency[source].append(target)
        reverse[target].append(source)
        outgoing_edges[source].append(edge)
        incoming_edges[target].append(edge)

    for node_id, node in nodes_by_id.items():
        if node["type"] != "start" and not incoming_edges[node_id]:
            issues.append(
                CompilationIssue(f"nodes.{node_id}", "非 start 节点必须有入边")
            )
        if node["type"] == "end" and outgoing_edges[node_id]:
            issues.append(CompilationIssue(f"nodes.{node_id}", "end 节点不能有出边"))
        if node["type"] == "condition":
            _validate_condition(node, nodes_by_id, incoming_edges, issues)
        elif node["type"] == "hermes_agent":
            _validate_hermes(node, issues)
        elif node["type"] == "loop":
            _validate_loop(
                node,
                issues,
                nested=nested,
                inherited_variables=variables,
            )

    for edge_id, edge in edges_by_id.items():
        source = nodes_by_id.get(edge["source_node_id"])
        if source is None:
            continue
        source_port = edge.get("source_port", "default")
        if source["type"] == "condition":
            ports = _condition_ports(source.get("config") or {})
            if source_port not in ports:
                issues.append(
                    CompilationIssue(
                        f"edges.{edge_id}.source_port", "Condition 输出端口不存在"
                    )
                )
        elif source_port != "default":
            issues.append(
                CompilationIssue(
                    f"edges.{edge_id}.source_port", "当前节点仅支持 default 输出端口"
                )
            )
        if edge.get("target_port", "default") != "default":
            issues.append(
                CompilationIssue(
                    f"edges.{edge_id}.target_port", "当前节点仅支持 default 输入端口"
                )
            )

    if start_ids:
        _validate_reachability(start_ids[0], end_ids, adjacency, reverse, issues)
    topo = _topological_order(adjacency, reverse, issues)
    limits = _normalize_limits(raw.get("limits") or {}, issues)

    if issues:
        raise WorkflowCompilationError(issues)

    compiled_nodes: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes_by_id.items():
        item = {
            "id": node_id,
            "type": node["type"],
            "type_version": node["type_version"],
            "executor_version": node["executor_version"],
            "config": node["config"],
        }
        if node["type"] == "loop":
            body = node["config"]["body"]
            body_compiled = compile_workflow(
                body,
                nested=True,
                inherited_variables=variables,
            )
            item["body_plan"] = body_compiled.plan
            item["body_checksum"] = body_compiled.checksum
        compiled_nodes[node_id] = item

    plan = {
        "engine_version": 2,
        "schema_version": 2,
        "root_node_id": start_ids[0],
        "end_node_ids": end_ids,
        "nodes": compiled_nodes,
        "edges": edges_by_id,
        "adjacency": adjacency,
        "reverse_adjacency": reverse,
        "outgoing_edge_ids": {
            key: [edge["id"] for edge in value] for key, value in outgoing_edges.items()
        },
        "incoming_edge_ids": {
            key: [edge["id"] for edge in value] for key, value in incoming_edges.items()
        },
        "topological_order": topo,
        "limits": limits,
        "variables": variables,
        "join_policy": "all_resolved",
    }
    canonical = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return CompiledWorkflow(definition=raw, plan=plan, checksum=checksum)


def ensure_workflow_dsl_v2(definition: Any) -> None:
    """Public guard for execution paths that read an already-published snapshot."""
    _ensure_v2_document(definition)
    _reject_removed_v1_fields(definition)


def _ensure_v2_document(definition: Any | WorkflowDefinition) -> None:
    if isinstance(definition, WorkflowDefinition):
        version = definition.schema_version
    elif isinstance(definition, dict):
        version = definition.get("schema_version")
    else:
        return
    if version is None or version == 1:
        raise UnsupportedWorkflowDslError(
            [
                CompilationIssue(
                    "schema_version", "不支持 DSL v1；仅支持 schema_version=2"
                )
            ]
        )
    if version != 2:
        raise WorkflowCompilationError(
            [CompilationIssue("schema_version", "仅支持 schema_version=2")]
        )


def _reject_removed_v1_fields(definition: Any | WorkflowDefinition) -> None:
    raw = (
        definition.model_dump(mode="json", exclude_none=True)
        if isinstance(definition, WorkflowDefinition)
        else definition
    )
    if not isinstance(raw, dict):
        return
    issues: list[CompilationIssue] = []
    _collect_removed_v1_fields(raw, prefix="", issues=issues)
    if issues:
        raise UnsupportedWorkflowDslError(issues)


def _collect_removed_v1_fields(
    definition: dict[str, Any], *, prefix: str, issues: list[CompilationIssue]
) -> None:
    """Reject V1-only fields at every DSL level before Pydantic normalizes them."""
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        path = f"{prefix}nodes[{index}]"
        for field in sorted(_REMOVED_V1_NODE_FIELDS & set(node)):
            issues.append(CompilationIssue(f"{path}.{field}", f"DSL v2 不支持 {field}"))
        node_type = node.get("type")
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        for field in sorted(
            _REMOVED_V1_CONFIG_FIELDS.get(node_type, frozenset()) & set(config)
        ):
            issues.append(
                CompilationIssue(f"{path}.config.{field}", f"DSL v2 不支持 {field}")
            )
        if node_type != "loop":
            continue
        termination = config.get("termination")
        if isinstance(termination, dict):
            for field in sorted(_REMOVED_V1_LOOP_TERMINATION_FIELDS & set(termination)):
                issues.append(
                    CompilationIssue(
                        f"{path}.config.termination.{field}",
                        f"DSL v2 不支持 {field}",
                    )
                )
        body = config.get("body")
        if isinstance(body, dict):
            _collect_removed_v1_fields(
                body, prefix=f"{path}.config.body.", issues=issues
            )


def _validate_variables(
    variables: dict[str, dict[str, Any]], issues: list[CompilationIssue]
) -> None:
    for name, definition in variables.items():
        if not _VARIABLE_NAME.fullmatch(name):
            issues.append(
                CompilationIssue(
                    f"variables.{name}", "变量名必须以字母开头且只含字母、数字或下划线"
                )
            )
        if not isinstance(definition, dict) or definition.get("type") not in {
            "string",
            "integer",
            "number",
            "boolean",
            "object",
            "array",
            "null",
        }:
            issues.append(CompilationIssue(f"variables.{name}", "变量类型无效"))


def _validate_condition(
    node: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    incoming_edges: dict[str, list[dict[str, Any]]],
    issues: list[CompilationIssue],
) -> None:
    config = node["config"]
    mode = config.get("mode")
    if mode not in {"agent", "formula"}:
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.mode",
                "condition mode 必须为 agent 或 formula",
            )
        )
        return
    ports = config.get("ports")
    if not isinstance(ports, list) or len(ports) < 2:
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.ports", "condition 至少需要两个唯一输出端口"
            )
        )
        return
    seen: set[str] = set()
    for index, port in enumerate(ports):
        if not isinstance(port, str) or not port.strip() or port in seen:
            issues.append(
                CompilationIssue(
                    f"nodes.{node['id']}.config.ports[{index}]",
                    "condition 端口必须是唯一非空字符串",
                )
            )
            continue
        seen.add(port)
    if mode == "agent":
        incoming = incoming_edges.get(node["id"], [])
        if len(incoming) != 1:
            issues.append(
                CompilationIssue(
                    f"nodes.{node['id']}",
                    "agent condition 必须只有一个直接 Hermes 上游",
                )
            )
            return
        source = nodes.get(incoming[0]["source_node_id"])
        if source is None or source.get("type") != "hermes_agent":
            issues.append(
                CompilationIssue(
                    f"nodes.{node['id']}",
                    "agent condition 的直接上游必须是 hermes_agent",
                )
            )
        return
    expression = config.get("expression")
    if "expression" not in config:
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.expression",
                "formula condition 需要 expression",
            )
        )
    try:
        validate_expression(expression, allowed_path_roots={"vars", "system"})
    except ExpressionError as exc:
        issues.append(
            CompilationIssue(f"nodes.{node['id']}.config.expression", str(exc))
        )
    true_port = config.get("true_port")
    false_port = config.get("false_port")
    if (
        not isinstance(true_port, str)
        or not isinstance(false_port, str)
        or true_port == false_port
        or true_port not in seen
        or false_port not in seen
    ):
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config",
                "formula condition 需要 ports 中不同的 true_port 和 false_port",
            )
        )


def _condition_ports(config: dict[str, Any]) -> set[str]:
    ports = config.get("ports")
    if not isinstance(ports, list):
        return set()
    return {port for port in ports if isinstance(port, str)}


def _validate_hermes(node: dict[str, Any], issues: list[CompilationIssue]) -> None:
    config = node["config"]
    instance_id = config.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip():
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.instance_id",
                "hermes_agent 需要 instance_id",
            )
        )
    prompt = config.get("prompt")
    messages = config.get("messages")
    if not isinstance(prompt, str) and not isinstance(messages, list):
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config", "hermes_agent 需要 prompt 或 messages"
            )
        )


def _validate_loop(
    node: dict[str, Any],
    issues: list[CompilationIssue],
    *,
    nested: bool,
    inherited_variables: dict[str, dict[str, Any]],
) -> None:
    if nested:
        issues.append(CompilationIssue(f"nodes.{node['id']}", "首期不支持嵌套 loop"))
        return
    config = node["config"]
    body = config.get("body")
    body_definition: dict[str, Any] | None = None
    if not isinstance(body, dict):
        issues.append(
            CompilationIssue(f"nodes.{node['id']}.config.body", "loop 需要 body 工作流")
        )
    else:
        try:
            body_compiled = compile_workflow(
                body, nested=True, inherited_variables=inherited_variables
            )
        except WorkflowCompilationError as exc:
            for issue in exc.issues:
                issues.append(
                    CompilationIssue(
                        f"nodes.{node['id']}.config.body.{issue.path}", issue.message
                    )
                )
        else:
            body_definition = body_compiled.definition
            end_count = sum(
                1 for item in body_definition["nodes"] if item["type"] == "end"
            )
            if end_count != 1:
                issues.append(
                    CompilationIssue(
                        f"nodes.{node['id']}.config.body.nodes",
                        "Loop Body 必须且只能有一个 end 节点",
                    )
                )
    termination = config.get("termination")
    if not isinstance(termination, dict):
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.termination", "loop 需要 termination"
            )
        )
    else:
        mode = termination.get("mode")
        if mode == "formula":
            if "expression" not in termination:
                issues.append(
                    CompilationIssue(
                        f"nodes.{node['id']}.config.termination.expression",
                        "formula loop termination 需要 expression",
                    )
                )
            try:
                validate_expression(
                    termination.get("expression"),
                    allowed_path_roots={"vars", "system"},
                )
            except ExpressionError as exc:
                issues.append(
                    CompilationIssue(
                        f"nodes.{node['id']}.config.termination.expression", str(exc)
                    )
                )
        elif mode == "agent":
            source_node_id = termination.get("source_node_id")
            body_nodes = {
                item.get("id"): item
                for item in (body_definition or {}).get("nodes", [])
                if isinstance(item, dict)
            }
            if (
                not isinstance(source_node_id, str)
                or body_nodes.get(source_node_id, {}).get("type") != "hermes_agent"
            ):
                issues.append(
                    CompilationIssue(
                        f"nodes.{node['id']}.config.termination.source_node_id",
                        "agent loop termination 需要 Body 内 hermes_agent source_node_id",
                    )
                )
        else:
            issues.append(
                CompilationIssue(
                    f"nodes.{node['id']}.config.termination.mode",
                    "loop termination mode 必须为 agent 或 formula",
                )
            )
    limits = config.get("limits")
    if (
        not isinstance(limits, dict)
        or not isinstance(limits.get("max_iterations"), int)
        or limits["max_iterations"] < 1
    ):
        issues.append(
            CompilationIssue(
                f"nodes.{node['id']}.config.limits.max_iterations",
                "loop 需要正整数 max_iterations",
            )
        )


def _validate_reachability(
    root: str,
    end_ids: list[str],
    adjacency: dict[str, list[str]],
    reverse: dict[str, list[str]],
    issues: list[CompilationIssue],
) -> None:
    reachable = _walk(root, adjacency)
    for node_id in adjacency:
        if node_id not in reachable:
            issues.append(CompilationIssue(f"nodes.{node_id}", "节点从 start 不可达"))
    can_reach_end: set[str] = set()
    for end_id in end_ids:
        can_reach_end |= _walk(end_id, reverse)
    for node_id in adjacency:
        if node_id not in can_reach_end:
            issues.append(CompilationIssue(f"nodes.{node_id}", "节点无法到达 end"))


def _walk(root: str, adjacency: dict[str, list[str]]) -> set[str]:
    result: set[str] = set()
    stack = [root]
    while stack:
        node_id = stack.pop()
        if node_id in result:
            continue
        result.add(node_id)
        stack.extend(adjacency.get(node_id, []))
    return result


def _topological_order(
    adjacency: dict[str, list[str]],
    reverse: dict[str, list[str]],
    issues: list[CompilationIssue],
) -> list[str]:
    indegree = {node_id: len(reverse[node_id]) for node_id in adjacency}
    ready = sorted(node_id for node_id, value in indegree.items() if value == 0)
    result: list[str] = []
    while ready:
        node_id = ready.pop(0)
        result.append(node_id)
        for target in adjacency[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(result) != len(adjacency):
        cyclic = sorted(node_id for node_id, value in indegree.items() if value > 0)
        issues.append(CompilationIssue("edges", f"工作流包含环：{', '.join(cyclic)}"))
    return result


def _normalize_limits(
    raw: dict[str, Any], issues: list[CompilationIssue]
) -> dict[str, int]:
    result = dict(DEFAULT_LIMITS)
    for key in DEFAULT_LIMITS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, int) or value < 1:
            issues.append(CompilationIssue(f"limits.{key}", "必须是正整数"))
            continue
        result[key] = value
    return result


def _pydantic_issues(exc: ValidationError) -> list[CompilationIssue]:
    """Expose schema shape failures in the compiler's value-free issue form."""
    issues: list[CompilationIssue] = []
    for error in exc.errors():
        location = error.get("loc") or ()
        parts: list[str] = []
        for item in location:
            if isinstance(item, int):
                if parts:
                    parts[-1] = f"{parts[-1]}[{item}]"
                else:
                    parts.append(f"[{item}]")
            else:
                parts.append(str(item))
        issues.append(
            CompilationIssue(".".join(parts) or "definition", "工作流定义字段无效")
        )
    return issues or [CompilationIssue("definition", "工作流定义字段无效")]

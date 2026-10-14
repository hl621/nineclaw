"""Unit coverage for the one-way version-2 workflow compiler."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.workflow.compiler import (
    UnsupportedWorkflowDslError,
    WorkflowCompilationError,
    compile_workflow,
)


START_ID = "start_0000000000004001"
AGENT_ID = "hermes_agent_0000000000004002"
END_ID = "end_0000000000004003"
CONDITION_ID = "condition_0000000000004004"
LOOP_ID = "loop_0000000000004005"
SECOND_END_ID = "end_0000000000004006"


def _node(node_id: str, node_type: str, config: dict | None = None) -> dict:
    return {"id": node_id, "type": node_type, "config": config or {}}


def _definition(*, instance_id: str = "agent-instance") -> dict:
    return {
        "schema_version": 2,
        "variables": {
            "approved": {"type": "boolean", "description": "是否批准"},
            "summary": {"type": "string"},
        },
        "nodes": [
            _node(START_ID, "start"),
            _node(
                AGENT_ID,
                "hermes_agent",
                {"instance_id": instance_id, "prompt": "处理任务"},
            ),
            _node(END_ID, "end"),
        ],
        "edges": [
            {
                "id": "start-agent",
                "source_node_id": START_ID,
                "target_node_id": AGENT_ID,
            },
            {
                "id": "agent-end",
                "source_node_id": AGENT_ID,
                "target_node_id": END_ID,
            },
        ],
    }


def _condition_definition(*, mode: str) -> dict:
    definition = _definition()
    if mode == "agent":
        config = {"mode": "agent", "ports": ["approved", "rejected"]}
    else:
        config = {
            "mode": "formula",
            "ports": ["approved", "rejected"],
            "expression": {"eq": [{"path": "vars.approved"}, True]},
            "true_port": "approved",
            "false_port": "rejected",
        }
    definition["nodes"] = [
        definition["nodes"][0],
        definition["nodes"][1],
        _node(CONDITION_ID, "condition", config),
        _node(END_ID, "end"),
        _node(SECOND_END_ID, "end"),
    ]
    definition["edges"] = [
        {
            "id": "start-agent",
            "source_node_id": START_ID,
            "target_node_id": AGENT_ID,
        },
        {
            "id": "agent-condition",
            "source_node_id": AGENT_ID,
            "target_node_id": CONDITION_ID,
        },
        {
            "id": "condition-approved",
            "source_node_id": CONDITION_ID,
            "source_port": "approved",
            "target_node_id": END_ID,
        },
        {
            "id": "condition-rejected",
            "source_node_id": CONDITION_ID,
            "source_port": "rejected",
            "target_node_id": SECOND_END_ID,
        },
    ]
    return definition


def _loop_body(instance_id: str = "agent-instance") -> dict:
    return {
        "schema_version": 2,
        "nodes": [
            _node("start_0000000000004011", "start"),
            _node(
                "hermes_agent_0000000000004012",
                "hermes_agent",
                {"instance_id": instance_id, "prompt": "迭代任务"},
            ),
            _node("end_0000000000004013", "end"),
        ],
        "edges": [
            {
                "id": "body-start-agent",
                "source_node_id": "start_0000000000004011",
                "target_node_id": "hermes_agent_0000000000004012",
            },
            {
                "id": "body-agent-end",
                "source_node_id": "hermes_agent_0000000000004012",
                "target_node_id": "end_0000000000004013",
            },
        ],
    }


def test_compile_v2_builds_artifact_and_variable_plan_without_mapping_fields():
    compiled = compile_workflow(_definition())

    assert compiled.definition["schema_version"] == 2
    assert compiled.plan["engine_version"] == 2
    assert compiled.plan["variables"] == {
        "approved": {"type": "boolean", "description": "是否批准"},
        "summary": {"type": "string"},
    }
    agent = compiled.plan["nodes"][AGENT_ID]
    assert set(agent) == {"id", "type", "type_version", "executor_version", "config"}


def test_v1_is_rejected_with_stable_error_before_structural_validation():
    legacy = _definition()
    legacy["schema_version"] = 1

    with pytest.raises(UnsupportedWorkflowDslError) as exc_info:
        compile_workflow(legacy)

    assert exc_info.value.code == "WORKFLOW_DSL_V1_UNSUPPORTED"
    assert exc_info.value.issues[0].path == "schema_version"


@pytest.mark.parametrize("field", ["input_mapping", "input_schema", "output_schema"])
def test_v2_rejects_removed_mapping_and_schema_fields(field: str):
    definition = _definition()
    definition["nodes"][1][field] = {}

    with pytest.raises(UnsupportedWorkflowDslError) as exc_info:
        compile_workflow(definition)

    assert exc_info.value.issues[0].path == f"nodes[1].{field}"


def test_v2_rejects_removed_condition_and_loop_control_fields_recursively():
    condition = _condition_definition(mode="formula")
    condition["nodes"][2]["config"]["branches"] = []
    with pytest.raises(UnsupportedWorkflowDslError) as exc_info:
        compile_workflow(condition)
    assert exc_info.value.issues[0].path == "nodes[2].config.branches"

    definition = _definition()
    definition["nodes"] = [
        _node(START_ID, "start"),
        _node(
            LOOP_ID,
            "loop",
            {
                "body": _loop_body(),
                "termination": {
                    "mode": "formula",
                    "expression": {"eq": [{"path": "vars.approved"}, False]},
                },
                "limits": {"max_iterations": 2},
            },
        ),
        _node(END_ID, "end"),
    ]
    definition["edges"] = [
        {"id": "start-loop", "source_node_id": START_ID, "target_node_id": LOOP_ID},
        {"id": "loop-end", "source_node_id": LOOP_ID, "target_node_id": END_ID},
    ]

    for path, mutate in (
        (
            "nodes[1].config.mode",
            lambda value: value["nodes"][1]["config"].update({"mode": "stateful"}),
        ),
        (
            "nodes[1].config.termination.continue_when",
            lambda value: value["nodes"][1]["config"]["termination"].update(
                {"continue_when": True}
            ),
        ),
        (
            "nodes[1].config.body.nodes[1].input_mapping",
            lambda value: value["nodes"][1]["config"]["body"]["nodes"][1].update(
                {"input_mapping": {}}
            ),
        ),
    ):
        invalid = deepcopy(definition)
        mutate(invalid)
        with pytest.raises(UnsupportedWorkflowDslError) as exc_info:
            compile_workflow(invalid)
        assert exc_info.value.issues[0].path == path


def test_variable_contract_rejects_invalid_name():
    definition = _definition()
    definition["variables"] = {"invalid-name": {"type": "string"}}

    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(definition)

    assert any(
        issue.path == "variables.invalid-name" for issue in exc_info.value.issues
    )


def test_formula_condition_only_reads_vars_and_system_context():
    compiled = compile_workflow(_condition_definition(mode="formula"))

    assert compiled.plan["nodes"][CONDITION_ID]["config"]["mode"] == "formula"

    invalid = _condition_definition(mode="formula")
    invalid["nodes"][2]["config"]["expression"] = {"path": "output.secret"}
    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(invalid)
    assert any("expression" in issue.path for issue in exc_info.value.issues)


def test_agent_condition_requires_one_direct_hermes_parent_and_explicit_ports():
    compiled = compile_workflow(_condition_definition(mode="agent"))
    assert compiled.plan["nodes"][CONDITION_ID]["config"]["ports"] == [
        "approved",
        "rejected",
    ]

    invalid = _condition_definition(mode="agent")
    invalid["edges"][1]["source_node_id"] = START_ID
    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(invalid)
    assert any("直接上游" in issue.message for issue in exc_info.value.issues)


def test_formula_loop_inherits_root_variable_contract_into_body_plan():
    definition = _definition()
    definition["nodes"] = [
        _node(START_ID, "start"),
        _node(
            LOOP_ID,
            "loop",
            {
                "body": _loop_body(),
                "termination": {
                    "mode": "formula",
                    "expression": {"eq": [{"path": "vars.approved"}, False]},
                },
                "limits": {"max_iterations": 3},
            },
        ),
        _node(END_ID, "end"),
    ]
    definition["edges"] = [
        {
            "id": "start-loop",
            "source_node_id": START_ID,
            "target_node_id": LOOP_ID,
        },
        {
            "id": "loop-end",
            "source_node_id": LOOP_ID,
            "target_node_id": END_ID,
        },
    ]

    compiled = compile_workflow(definition)

    assert (
        compiled.plan["nodes"][LOOP_ID]["body_plan"]["variables"]
        == definition["variables"]
    )


def test_loop_body_requires_exactly_one_end_node():
    definition = _definition()
    body = _loop_body()
    second_end_id = "end_0000000000004014"
    body["nodes"].append(_node(second_end_id, "end"))
    body["edges"].append(
        {
            "id": "body-agent-second-end",
            "source_node_id": "hermes_agent_0000000000004012",
            "target_node_id": second_end_id,
        }
    )
    definition["nodes"] = [
        _node(START_ID, "start"),
        _node(
            LOOP_ID,
            "loop",
            {
                "body": body,
                "termination": {
                    "mode": "formula",
                    "expression": {"eq": [{"path": "vars.approved"}, False]},
                },
                "limits": {"max_iterations": 3},
            },
        ),
        _node(END_ID, "end"),
    ]
    definition["edges"] = [
        {"id": "start-loop", "source_node_id": START_ID, "target_node_id": LOOP_ID},
        {"id": "loop-end", "source_node_id": LOOP_ID, "target_node_id": END_ID},
    ]

    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(definition)

    assert any(
        issue.path == f"nodes.{LOOP_ID}.config.body.nodes"
        and issue.message == "Loop Body 必须且只能有一个 end 节点"
        for issue in exc_info.value.issues
    )


def test_agent_loop_requires_a_body_hermes_source_node():
    definition = _definition()
    definition["nodes"] = [
        _node(START_ID, "start"),
        _node(
            LOOP_ID,
            "loop",
            {
                "body": _loop_body(),
                "termination": {
                    "mode": "agent",
                    "source_node_id": "hermes_agent_0000000000004012",
                },
                "limits": {"max_iterations": 1},
            },
        ),
        _node(END_ID, "end"),
    ]
    definition["edges"] = [
        {
            "id": "start-loop",
            "source_node_id": START_ID,
            "target_node_id": LOOP_ID,
        },
        {
            "id": "loop-end",
            "source_node_id": LOOP_ID,
            "target_node_id": END_ID,
        },
    ]

    compile_workflow(definition)

    invalid = deepcopy(definition)
    invalid["nodes"][1]["config"]["termination"]["source_node_id"] = END_ID
    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(invalid)
    assert any("source_node_id" in issue.path for issue in exc_info.value.issues)


def test_rejects_cycle_and_non_default_agent_output_port():
    definition = _definition()
    definition["edges"].append(
        {
            "id": "cycle",
            "source_node_id": AGENT_ID,
            "target_node_id": START_ID,
        }
    )
    definition["edges"][0]["source_port"] = "alternate"

    with pytest.raises(WorkflowCompilationError) as exc_info:
        compile_workflow(definition)

    assert any(issue.path == "edges" for issue in exc_info.value.issues)
    assert any(
        issue.path == "edges.start-agent.source_port" for issue in exc_info.value.issues
    )

"""No-database public contract tests for node-conversation API projections."""

from uuid import UUID

from app.api.routes.workflow_conversations import (
    _conversation_response,
    _event_response,
    _turn_response,
    router,
)
from app.models.workflow import (
    WorkflowNodeConversation,
    WorkflowNodeConversationEvent,
    WorkflowNodeConversationTurn,
)
from app.services.workflow.conversations import _remote_status


def test_node_conversation_public_projections_strip_manager_and_hermes_internals():
    conversation_id = UUID("00000000-0000-0000-0000-000000000001")
    turn_id = UUID("00000000-0000-0000-0000-000000000002")
    conversation = WorkflowNodeConversation(
        id=conversation_id,
        tenant_id="tenant-1",
        workflow_id=UUID("00000000-0000-0000-0000-000000000003"),
        workflow_version_id=UUID("00000000-0000-0000-0000-000000000004"),
        node_definition_id="hermes_agent_0123456789abcdef",
        instance_id="agent-1",
        remote_session_id="wfconv-private-session",
        node_snapshot={"config": {"api_key": "must-not-leak"}},
        status="uncertain",
        attention_reason="Bearer secret must-not-leak",
    )
    turn = WorkflowNodeConversationTurn(
        id=turn_id,
        tenant_id="tenant-1",
        conversation_id=conversation_id,
        turn_number=1,
        executor_instance_id="agent-1",
        user_message={
            "role": "user",
            "content": "研究这个主题",
            "execution_id": "must-not-leak",
        },
        assistant_message={
            "role": "assistant",
            "content": {
                "text": "结果",
                "execution_id": "must-not-leak",
                "bridge_token": "must-not-leak",
            },
            "remote_session_id": "must-not-leak",
        },
        status="failed",
        external_run_id="must-not-leak",
        error_code="HERMES_RUN_FAILED",
        error_message="gateway token must-not-leak",
    )
    event = WorkflowNodeConversationEvent(
        tenant_id="tenant-1",
        conversation_id=conversation_id,
        turn_id=turn_id,
        sequence=7,
        event_type="turn.failed",
        data={
            "turn_id": str(turn_id),
            "code": "HERMES_RUN_FAILED",
            "external_run_id": "must-not-leak",
            "execution_id": "must-not-leak",
            "bridge_token": "must-not-leak",
        },
    )

    conversation_data = _conversation_response(conversation).model_dump(mode="json")
    turn_data = _turn_response(turn).model_dump(mode="json")
    event_data = _event_response(event).model_dump(mode="json")

    assert set(conversation_data) == {
        "id",
        "workflow_id",
        "node_definition_id",
        "status",
        "attention_reason",
        "created_at",
        "updated_at",
    }
    assert conversation_data["attention_reason"] == "当前回合执行结果未知，需要人工处置"
    assert turn_data["user_message"] == {"role": "user", "content": "研究这个主题"}
    assert turn_data["assistant_message"] == {"role": "assistant", "content": "结果"}
    assert turn_data["error_message"] == "当前回合执行失败"
    assert event_data["data"] == {
        "turn_id": str(turn_id),
        "code": "HERMES_RUN_FAILED",
    }
    assert "must-not-leak" not in str(
        {"conversation": conversation_data, "turn": turn_data, "event": event_data}
    )


def test_node_conversation_router_exposes_only_manager_controlled_paths():
    paths = {route.path for route in router.routes}

    assert "/workflows/{workflow_id}/nodes/{node_id}/conversations" in paths
    assert "/workflow-conversations/{conversation_id}/turns" in paths
    assert "/workflow-conversations/{conversation_id}/events/stream" in paths
    assert (
        "/workflow-conversations/{conversation_id}/turns/{turn_id}/mark-failed" in paths
    )
    assert all("version" not in path for path in paths)


def test_conversation_status_parser_accepts_hermes_state_field():
    assert _remote_status({"state": "completed"}) == "completed"
    assert _remote_status({"data": {"state": "in-progress"}}) == "in_progress"

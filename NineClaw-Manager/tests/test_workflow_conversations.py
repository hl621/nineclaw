"""PostgreSQL tests for durable independent Agent-node conversations.

Set ``WORKFLOW_TEST_DATABASE_URL`` to a disposable PostgreSQL database migrated
through revision 025.  Each test runs inside a rolled-back outer transaction.
"""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.instance import ServiceInstance
from app.models.template import ServiceTemplate
from app.models.tenant import Tenant
from app.models.workflow import (
    Workflow,
    WorkflowNodeConversation,
    WorkflowNodeConversationJob,
    WorkflowNodeConversationTurn,
    WorkflowVersion,
    utcnow,
)
from app.services.hermes_gateway_service import GatewayError
from app.services.workflow import conversation_scheduler as scheduler_module
from app.services.workflow.conversation_events import replay_conversation_events
from app.services.workflow.conversation_scheduler import WorkflowConversationScheduler
from app.services.workflow.conversations import (
    ConversationConflictError,
    ConversationValidationError,
    ConversationDispatch,
    WorkflowConversationService,
)
from app.services.workflow.compiler import compile_workflow


WORKFLOW_TEST_DATABASE_URL = os.getenv("WORKFLOW_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not WORKFLOW_TEST_DATABASE_URL,
    reason="需要 WORKFLOW_TEST_DATABASE_URL 指向已迁移的 PostgreSQL",
)


@pytest_asyncio.fixture
async def conversation_sessions():
    engine: AsyncEngine = create_async_engine(WORKFLOW_TEST_DATABASE_URL)
    connection: AsyncConnection = await engine.connect()
    outer_transaction = await connection.begin()
    sessions = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield sessions
    finally:
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


def _node_id(node_type: str) -> str:
    return f"{node_type}_{uuid4().hex[:16]}"


def _definition(instance_id: str) -> tuple[dict, str]:
    start_id = _node_id("start")
    agent_id = _node_id("hermes_agent")
    end_id = _node_id("end")
    return (
        {
            "schema_version": 2,
            "nodes": [
                {"id": start_id, "type": "start"},
                {
                    "id": agent_id,
                    "type": "hermes_agent",
                    "config": {
                        "instance_id": instance_id,
                        "model": "hermes-agent",
                        "prompt": "遵循此节点的既定指令。",
                    },
                },
                {"id": end_id, "type": "end"},
            ],
            "edges": [
                {
                    "id": f"edge-{uuid4().hex[:16]}",
                    "source_node_id": start_id,
                    "target_node_id": agent_id,
                },
                {
                    "id": f"edge-{uuid4().hex[:16]}",
                    "source_node_id": agent_id,
                    "target_node_id": end_id,
                },
            ],
        },
        agent_id,
    )


async def _create_conversation(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[str, UUID, UUID, str]:
    tenant_id = f"conversation-test-{uuid4().hex[:20]}"
    instance_id = f"agent-{uuid4().hex[:16]}"
    definition, agent_id = _definition(instance_id)
    compiled = compile_workflow(definition)
    async with sessions() as session:
        session.add(Tenant(id=tenant_id, name="conversation test", api_key_hash="test"))
        template = ServiceTemplate(
            name=f"conversation-{uuid4().hex}", image="test:latest"
        )
        session.add(template)
        await session.flush()
        session.add(
            ServiceInstance(
                id=instance_id,
                tenant_id=tenant_id,
                template_id=template.id,
                name=instance_id,
                desired_state="running",
                actual_state="running",
            )
        )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=f"workflow-{uuid4().hex}",
            draft_definition=compiled.definition,
            current_version_number=1,
        )
        session.add(workflow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=tenant_id,
                workflow_id=workflow.id,
                version_number=1,
                definition=compiled.definition,
                compiled_plan=compiled.plan,
                checksum=compiled.checksum,
            )
        )
        await session.flush()
        conversation = await WorkflowConversationService(session).create_conversation(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            node_definition_id=agent_id,
        )
        await session.commit()
        return tenant_id, workflow.id, conversation.id, instance_id


async def _create_legacy_v1_conversation(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[str, UUID, str]:
    """Persist a pre-cutover conversation without invoking the v2 API."""

    tenant_id = f"legacy-conversation-test-{uuid4().hex[:20]}"
    instance_id = f"agent-{uuid4().hex[:16]}"
    node_id = _node_id("hermes_agent")
    legacy_definition = {"schema_version": 1}
    async with sessions() as session:
        session.add(
            Tenant(id=tenant_id, name="legacy conversation", api_key_hash="test")
        )
        template = ServiceTemplate(name=f"legacy-{uuid4().hex}", image="test:latest")
        session.add(template)
        await session.flush()
        session.add(
            ServiceInstance(
                id=instance_id,
                tenant_id=tenant_id,
                template_id=template.id,
                name=instance_id,
                desired_state="running",
                actual_state="running",
            )
        )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=f"legacy-workflow-{uuid4().hex}",
            draft_definition=legacy_definition,
            current_version_number=1,
        )
        session.add(workflow)
        await session.flush()
        version = WorkflowVersion(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            version_number=1,
            definition=legacy_definition,
            compiled_plan={},
            checksum="0" * 64,
        )
        session.add(version)
        await session.flush()
        conversation = WorkflowNodeConversation(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            node_definition_id=node_id,
            instance_id=instance_id,
            remote_session_id=f"legacy-conversation-{uuid4().hex}",
            node_snapshot={
                "id": node_id,
                "type": "hermes_agent",
                "config": {"instance_id": instance_id, "prompt": "历史对话"},
            },
        )
        session.add(conversation)
        await session.commit()
        return tenant_id, conversation.id, instance_id


class _FakeGateway:
    create_payload: object = {"run_id": "hermes-conversation-1"}
    auto_increment_run_ids = True
    monitor_payloads: list[object] = [{"status": "succeeded", "output": "完成"}]
    create_call_args: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monitor_calls: list[str] = []
    approval_calls: list[tuple[str, str, str | None]] = []
    approval_payload: object = {"accepted": True}
    stop_calls: list[str] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def create_run(self, *_args, **_kwargs):
        type(self).create_call_args.append((_args, _kwargs))
        if isinstance(type(self).create_payload, Exception):
            raise type(self).create_payload
        if type(self).auto_increment_run_ids and isinstance(
            type(self).create_payload, dict
        ):
            return {
                **type(self).create_payload,
                "run_id": f"hermes-conversation-{len(type(self).create_call_args)}",
            }
        return type(self).create_payload

    async def get_run(self, run_id: str):
        type(self).monitor_calls.append(run_id)
        payloads = type(self).monitor_payloads
        payload = payloads.pop(0) if len(payloads) > 1 else payloads[0]
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def approve_run(self, run_id: str, decision: str, reason: str | None = None):
        type(self).approval_calls.append((run_id, decision, reason))
        if isinstance(type(self).approval_payload, Exception):
            raise type(self).approval_payload
        return type(self).approval_payload

    async def stop_run(self, run_id: str):
        type(self).stop_calls.append(run_id)
        return {"accepted": True}


def _reset_gateway(
    *,
    create_payload: object | None = None,
    monitor_payloads: list[object] | None = None,
    approval_payload: object | None = None,
) -> None:
    _FakeGateway.create_payload = (
        {"run_id": "hermes-conversation-1"}
        if create_payload is None
        else create_payload
    )
    _FakeGateway.auto_increment_run_ids = create_payload is None
    _FakeGateway.monitor_payloads = (
        [{"status": "succeeded", "output": "完成"}]
        if monitor_payloads is None
        else list(monitor_payloads)
    )
    _FakeGateway.create_call_args = []
    _FakeGateway.monitor_calls = []
    _FakeGateway.approval_calls = []
    _FakeGateway.approval_payload = (
        {"accepted": True} if approval_payload is None else approval_payload
    )
    _FakeGateway.stop_calls = []


@pytest.mark.asyncio
async def test_turns_are_serial_and_share_stable_session_without_workspace_identity(
    conversation_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        first = await service.start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="第一条消息",
        )
        with pytest.raises(ConversationConflictError):
            await service.start_turn(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message="不能并发发送",
            )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()  # dispatch first turn
    assert await scheduler.run_once()  # monitor first turn

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        refreshed_first = await service.get_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=first.id,
        )
        assert refreshed_first.status == "succeeded"
        assert refreshed_first.assistant_message == {
            "role": "assistant",
            "content": "完成",
        }
        assert not hasattr(refreshed_first, "execution_id")
        second = await service.start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="第二条消息",
        )
        await session.commit()

    assert await scheduler.run_once()  # dispatch second turn
    assert await scheduler.run_once()  # monitor second turn
    assert [args[1]["session_id"] for args in _FakeGateway.create_call_args] == [
        _FakeGateway.create_call_args[0][1]["session_id"],
        _FakeGateway.create_call_args[0][1]["session_id"],
    ]
    assert all(
        "execution_id" not in kwargs for _, kwargs in _FakeGateway.create_call_args
    )
    assert all(
        "workspace" not in str(kwargs.get("instructions") or "").lower()
        for _, kwargs in _FakeGateway.create_call_args
    )

    async with conversation_sessions() as session:
        turns = await WorkflowConversationService(session).list_turns(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        conversation = await session.get(WorkflowNodeConversation, conversation_id)
        assert [turn.turn_number for turn in turns] == [1, 2]
        assert all(turn.status == "succeeded" for turn in turns)
        assert conversation is not None
        assert (
            conversation.remote_session_id
            == _FakeGateway.create_call_args[0][1]["session_id"]
        )


@pytest.mark.asyncio
async def test_ambiguous_dispatch_becomes_uncertain_and_is_never_retried(
    conversation_sessions, monkeypatch
):
    _reset_gateway(create_payload=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="可能超时的请求",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()
    assert not await scheduler.run_once()

    async with conversation_sessions() as session:
        conversation = await session.get(WorkflowNodeConversation, conversation_id)
        refreshed_turn = await session.get(WorkflowNodeConversationTurn, turn.id)
        job = await session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "dispatch_turn",
            )
        )
        assert (
            conversation is not None and refreshed_turn is not None and job is not None
        )
        assert conversation.status == "uncertain"
        assert refreshed_turn.status == "uncertain"
        assert job.status == "uncertain"
        assert len(_FakeGateway.create_call_args) == 1


@pytest.mark.asyncio
async def test_reclaimed_dispatch_job_becomes_uncertain_without_second_create(
    conversation_sessions, monkeypatch
):
    """A crashed Worker cannot safely replay an unconfirmed Hermes create."""

    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="模拟 Worker 在 Hermes 创建期间崩溃",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    first_claim = await scheduler._claim_one()
    assert first_claim is not None
    assert not first_claim.reclaimed
    async with conversation_sessions() as session:
        job = await session.get(WorkflowNodeConversationJob, first_claim.id)
        assert job is not None
        prepared = await WorkflowConversationService(session).prepare_dispatch(
            job=job,
            fencing_token=first_claim.fencing_token,
            reclaimed=first_claim.reclaimed,
        )
        assert prepared is not None
        await session.commit()

    async with conversation_sessions() as session:
        job = await session.get(WorkflowNodeConversationJob, first_claim.id)
        assert job is not None
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        await session.commit()

    assert await scheduler.run_once()
    assert _FakeGateway.create_call_args == []
    async with conversation_sessions() as session:
        conversation = await session.get(WorkflowNodeConversation, conversation_id)
        refreshed_turn = await session.get(WorkflowNodeConversationTurn, turn.id)
        job = await session.get(WorkflowNodeConversationJob, first_claim.id)
        assert (
            conversation is not None and refreshed_turn is not None and job is not None
        )
        assert conversation.status == "uncertain"
        assert refreshed_turn.status == "uncertain"
        assert job.status == "uncertain"


@pytest.mark.asyncio
async def test_approval_and_event_replay_persist_lifecycle_order(
    conversation_sessions, monkeypatch
):
    _reset_gateway(
        monitor_payloads=[
            {"status": "requires_action"},
            {"status": "succeeded", "output": {"content": "批准后完成"}},
        ]
    )
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="需要审批",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()  # dispatch
    assert await scheduler.run_once()  # monitor -> approval_required

    async with conversation_sessions() as session:
        approved_turn = await WorkflowConversationService(session).request_approval(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            decision="allow",
            reason="人工确认",
        )
        assert approved_turn.status == "approval_submitting"
        await session.commit()

    assert await scheduler.run_once()  # approve Run
    assert await scheduler.run_once()  # monitor -> success
    assert _FakeGateway.approval_calls == [
        ("hermes-conversation-1", "allow", "人工确认")
    ]

    async with conversation_sessions() as session:
        events = await replay_conversation_events(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        replay = await replay_conversation_events(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            after_sequence=events[2].sequence,
        )
        refreshed_turn = await session.get(WorkflowNodeConversationTurn, turn.id)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert "turn.approval_required" in [event.event_type for event in events]
        assert "turn.completed" in [event.event_type for event in events]
        assert [event.sequence for event in replay] == [
            event.sequence for event in events[3:]
        ]
        assert refreshed_turn is not None
        assert refreshed_turn.status == "succeeded"
        assert refreshed_turn.assistant_message == {
            "role": "assistant",
            "content": "批准后完成",
        }


@pytest.mark.asyncio
async def test_cancel_forwards_stop_for_known_run_without_new_dispatch(
    conversation_sessions, monkeypatch
):
    _reset_gateway(monitor_payloads=[{"status": "running"}])
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="需要取消",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()  # dispatch
    async with conversation_sessions() as session:
        await WorkflowConversationService(session).request_cancel(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            requested_by="tester",
        )
        await session.commit()

    assert await scheduler.run_once()  # old monitor -> running, then delayed
    assert await scheduler.run_once()  # cancel -> stop_run
    assert _FakeGateway.stop_calls == ["hermes-conversation-1"]
    assert len(_FakeGateway.create_call_args) == 1
    async with conversation_sessions() as session:
        refreshed_turn = await session.get(WorkflowNodeConversationTurn, turn.id)
        assert refreshed_turn is not None
        assert refreshed_turn.status == "cancel_requested"


@pytest.mark.asyncio
async def test_turn_idempotency_key_reuses_original_turn_without_second_hermes_run(
    conversation_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        first = await service.start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="可安全重试的请求",
            idempotency_key="turn-request-1",
        )
        replayed = await service.start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="可安全重试的请求",
            idempotency_key="turn-request-1",
        )
        assert replayed.id == first.id
        with pytest.raises(ConversationConflictError):
            await service.start_turn(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message="不同内容",
                idempotency_key="turn-request-1",
            )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()
    assert len(_FakeGateway.create_call_args) == 1


@pytest.mark.asyncio
async def test_state_payload_completes_conversation_turn(
    conversation_sessions, monkeypatch
):
    _reset_gateway(monitor_payloads=[{"state": "completed", "output": "已完成"}])
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="兼容 state 字段",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with conversation_sessions() as session:
        refreshed = await session.get(WorkflowNodeConversationTurn, turn.id)
        assert refreshed is not None
        assert refreshed.status == "succeeded"
        assert refreshed.assistant_message == {"role": "assistant", "content": "已完成"}


@pytest.mark.asyncio
async def test_duplicate_cancel_does_not_requeue_an_already_sent_stop(
    conversation_sessions, monkeypatch
):
    _reset_gateway(monitor_payloads=[{"status": "running"}])
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="只停止一次",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()
    async with conversation_sessions() as session:
        await WorkflowConversationService(session).request_cancel(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
        )
        await session.commit()
    assert await scheduler.run_once()
    assert await scheduler.run_once()
    assert _FakeGateway.stop_calls == ["hermes-conversation-1"]

    async with conversation_sessions() as session:
        cancel_job = await session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "cancel_turn",
            )
        )
        assert cancel_job is not None
        assert cancel_job.status == "succeeded"
        await WorkflowConversationService(session).request_cancel(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
        )
        await session.commit()
        await session.refresh(cancel_job)
        assert cancel_job.status == "succeeded"


@pytest.mark.asyncio
async def test_approval_rejection_restarts_read_only_monitoring(
    conversation_sessions, monkeypatch
):
    _reset_gateway(
        monitor_payloads=[
            {"status": "requires_action"},
            {"status": "expired"},
        ],
        approval_payload=GatewayError(422, "审批参数无效"),
    )
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="审批拒绝后仍应收敛",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()
    assert await scheduler.run_once()
    async with conversation_sessions() as session:
        await WorkflowConversationService(session).request_approval(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            decision="allow",
        )
        await session.commit()
    assert await scheduler.run_once()
    assert await scheduler.run_once()

    async with conversation_sessions() as session:
        refreshed = await session.get(WorkflowNodeConversationTurn, turn.id)
        assert refreshed is not None
        assert refreshed.status == "failed"


@pytest.mark.asyncio
async def test_operator_can_close_uncertain_turn_without_sending_another_hermes_call(
    conversation_sessions, monkeypatch
):
    _reset_gateway(create_payload=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, _workflow_id, conversation_id, _instance_id = await _create_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        turn = await WorkflowConversationService(session).start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="结果未知",
        )
        await session.commit()

    scheduler = WorkflowConversationScheduler(conversation_sessions)
    assert await scheduler.run_once()

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        resolved = await service.resolve_uncertain_as_failed(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            reason="运维确认本次结果按失败收敛",
        )
        next_turn = await service.start_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="人工处置后的新请求",
        )
        await session.commit()
        assert resolved.status == "failed"
        assert resolved.error_code == "MANUAL_UNCERTAIN_RESOLVED"
        assert next_turn.turn_number == 2
    assert len(_FakeGateway.create_call_args) == 1


@pytest.mark.asyncio
async def test_v1_conversation_rejects_new_turn_and_never_dispatches_queued_turn(
    conversation_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, conversation_id, instance_id = await _create_legacy_v1_conversation(
        conversation_sessions
    )

    async with conversation_sessions() as session:
        turn = WorkflowNodeConversationTurn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            executor_instance_id=instance_id,
            user_message={"role": "user", "content": "切换前排队的消息"},
        )
        session.add(turn)
        await session.flush()
        session.add(
            WorkflowNodeConversationJob(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_id=turn.id,
                job_type="dispatch_turn",
                dedupe_key=f"dispatch:{turn.id}",
                payload={},
            )
        )
        await session.commit()

    async with conversation_sessions() as session:
        with pytest.raises(
            ConversationValidationError, match="WORKFLOW_DSL_V1_UNSUPPORTED"
        ):
            await WorkflowConversationService(session).start_turn(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message="切换后新消息",
            )

    assert await WorkflowConversationScheduler(conversation_sessions).run_once()

    async with conversation_sessions() as session:
        refreshed = await session.get(WorkflowNodeConversationTurn, turn.id)
        job = await session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "dispatch_turn",
            )
        )
        assert refreshed is not None and job is not None
        assert refreshed.status == "failed"
        assert refreshed.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert job.status == "failed"
        assert _FakeGateway.create_call_args == []


@pytest.mark.asyncio
async def test_v1_cutover_after_remote_create_requests_stop_without_monitoring_output(
    conversation_sessions, monkeypatch
):
    _reset_gateway()
    monkeypatch.setattr(scheduler_module, "HermesGatewayService", _FakeGateway)
    tenant_id, conversation_id, instance_id = await _create_legacy_v1_conversation(
        conversation_sessions
    )

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        turn = WorkflowNodeConversationTurn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            executor_instance_id=instance_id,
            user_message={"role": "user", "content": "远端创建与切换并发"},
            status="dispatching",
        )
        session.add(turn)
        await session.flush()
        dispatch_job = WorkflowNodeConversationJob(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            job_type="dispatch_turn",
            status="running",
            dedupe_key=f"dispatch:{turn.id}",
            payload={},
            fencing_token=1,
        )
        session.add(dispatch_job)
        await session.flush()
        dispatch = ConversationDispatch(
            job_id=dispatch_job.id,
            fencing_token=1,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id,
            base_url="http://unused",
            api_key="",
            model="hermes-agent",
            messages=[turn.user_message],
            instructions=None,
            session_id="legacy-session",
            extra={},
        )
        await service.persist_dispatched(
            dispatch=dispatch,
            external_run_id="legacy-conversation-run",
        )
        await session.commit()

    async with conversation_sessions() as session:
        refreshed = await session.get(WorkflowNodeConversationTurn, turn.id)
        cancel_job = await session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "cancel_turn",
            )
        )
        monitor_job = await session.scalar(
            select(WorkflowNodeConversationJob).where(
                WorkflowNodeConversationJob.turn_id == turn.id,
                WorkflowNodeConversationJob.job_type == "monitor_turn",
            )
        )
        assert refreshed is not None and cancel_job is not None
        assert refreshed.external_run_id == "legacy-conversation-run"
        assert refreshed.status == "cancel_requested"
        assert refreshed.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert cancel_job.status == "queued"
        assert monitor_job is None

    assert await WorkflowConversationScheduler(conversation_sessions).run_once()

    async with conversation_sessions() as session:
        refreshed = await session.get(WorkflowNodeConversationTurn, turn.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error_code == "WORKFLOW_DSL_V1_UNSUPPORTED"
        assert _FakeGateway.stop_calls == ["legacy-conversation-run"]
        assert _FakeGateway.monitor_calls == []


@pytest.mark.asyncio
async def test_v1_conversation_rejects_approval_and_manual_resolution_without_jobs(
    conversation_sessions,
):
    tenant_id, conversation_id, instance_id = await _create_legacy_v1_conversation(
        conversation_sessions
    )
    async with conversation_sessions() as session:
        approval_turn = WorkflowNodeConversationTurn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            executor_instance_id=instance_id,
            user_message={"role": "user", "content": "等待审批"},
            status="approval_required",
            external_run_id="legacy-approval-run",
        )
        uncertain_turn = WorkflowNodeConversationTurn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=2,
            executor_instance_id=instance_id,
            user_message={"role": "user", "content": "结果未知"},
            status="uncertain",
        )
        session.add_all([approval_turn, uncertain_turn])
        await session.commit()

    async with conversation_sessions() as session:
        service = WorkflowConversationService(session)
        with pytest.raises(
            ConversationValidationError, match="WORKFLOW_DSL_V1_UNSUPPORTED"
        ):
            await service.request_approval(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_id=approval_turn.id,
                decision="allow",
            )
        with pytest.raises(
            ConversationValidationError, match="WORKFLOW_DSL_V1_UNSUPPORTED"
        ):
            await service.resolve_uncertain_as_failed(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_id=uncertain_turn.id,
                reason="不应修改历史版本",
            )
        await session.commit()

    async with conversation_sessions() as session:
        approval = await session.get(WorkflowNodeConversationTurn, approval_turn.id)
        uncertain = await session.get(WorkflowNodeConversationTurn, uncertain_turn.id)
        jobs = list(
            (
                await session.scalars(
                    select(WorkflowNodeConversationJob).where(
                        WorkflowNodeConversationJob.conversation_id == conversation_id
                    )
                )
            ).all()
        )
        assert approval is not None and uncertain is not None
        assert approval.status == "approval_required"
        assert uncertain.status == "uncertain"
        assert jobs == []

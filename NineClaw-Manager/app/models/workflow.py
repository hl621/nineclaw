"""Persistent workflow execution models.

The workflow engine owns durable definition, runtime and event state.  Hermes
is an external executor and its ``run_id`` is recorded on an Attempt only
after the manager receives a successful create response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel


def utcnow() -> datetime:
    """Return naive UTC for PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowNodeTypeDefinition(SQLModel, table=True):
    """Global, database-backed editor metadata for executable node types."""

    __tablename__ = "workflow_node_type_definitions"
    __table_args__ = (
        UniqueConstraint(
            "display_order", name="uq_workflow_node_type_definitions_display_order"
        ),
    )

    type: str = Field(primary_key=True, max_length=64)
    display_order: int = Field(sa_column=Column(Integer, nullable=False))
    definition: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )


class Workflow(SQLModel, table=True):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_workflows_tenant_name"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    name: str = Field(max_length=128, nullable=False)
    description: str = Field(default="", max_length=2048)
    draft_definition: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    draft_revision: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    current_version_number: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowVersion(SQLModel, table=True):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_versions_number"
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    version_number: int = Field(sa_column=Column(Integer, nullable=False))
    definition: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    compiled_plan: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    checksum: str = Field(max_length=64, nullable=False)
    created_at: datetime = Field(default_factory=utcnow)


class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    workflow_version_id: UUID = Field(foreign_key="workflow_versions.id", index=True)
    run_kind: str = Field(default="workflow", max_length=32, nullable=False)
    debug_node_id: str | None = Field(default=None, max_length=128)
    status: str = Field(default="queued", max_length=32, index=True)
    input: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    output: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    budget: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    event_seq: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    cancel_requested_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    cancel_requested_by: str | None = Field(default=None, max_length=128)
    attention_reason: str | None = Field(default=None, max_length=2048)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowScopeRun(SQLModel, table=True):
    __tablename__ = "workflow_scope_runs"
    __table_args__ = (
        UniqueConstraint(
            "parent_node_run_id", "iteration_index", name="uq_workflow_scope_iteration"
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    parent_scope_run_id: UUID | None = Field(default=None, index=True)
    parent_node_run_id: UUID | None = Field(default=None, index=True)
    kind: str = Field(default="root", max_length=32)
    iteration_index: int | None = Field(default=None)
    state: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="running", max_length=32, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class WorkflowNodeRun(SQLModel, table=True):
    __tablename__ = "workflow_node_runs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "scope_run_id",
            "node_definition_id",
            name="uq_workflow_node_run",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    scope_run_id: UUID = Field(foreign_key="workflow_scope_runs.id", index=True)
    node_definition_id: str = Field(max_length=128)
    node_type: str = Field(max_length=64)
    status: str = Field(default="pending", max_length=32, index=True)
    input_snapshot: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    output: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    variable_state: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    active_attempt_id: UUID | None = Field(default=None, index=True)
    generation: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class WorkflowEdgeRun(SQLModel, table=True):
    __tablename__ = "workflow_edge_runs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "scope_run_id",
            "edge_definition_id",
            name="uq_workflow_edge_run",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    scope_run_id: UUID = Field(foreign_key="workflow_scope_runs.id", index=True)
    edge_definition_id: str = Field(max_length=128)
    source_node_id: str = Field(max_length=128)
    source_port: str = Field(default="default", max_length=128)
    target_node_id: str = Field(max_length=128)
    target_port: str = Field(default="default", max_length=128)
    status: str = Field(default="pending", max_length=32, index=True)
    resolved_at: datetime | None = Field(default=None)


class WorkflowNodeAttempt(SQLModel, table=True):
    __tablename__ = "workflow_node_attempts"
    __table_args__ = (
        UniqueConstraint(
            "node_run_id", "generation", name="uq_workflow_attempt_generation"
        ),
        UniqueConstraint("execution_id", name="uq_workflow_attempt_execution_id"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    node_run_id: UUID = Field(foreign_key="workflow_node_runs.id", index=True)
    generation: int = Field(sa_column=Column(Integer, nullable=False))
    execution_id: str = Field(max_length=128, nullable=False, index=True)
    status: str = Field(default="prepared", max_length=32, index=True)
    executor_instance_id: str | None = Field(default=None, max_length=64, index=True)
    external_run_id: str | None = Field(default=None, max_length=256, index=True)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = Field(default=None)
    fencing_token: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class WorkflowVariableWrite(SQLModel, table=True):
    """One staged or committed variable value emitted by a node Attempt."""

    __tablename__ = "workflow_variable_writes"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "name", name="uq_workflow_variable_write_attempt_name"
        ),
        Index(
            "ix_workflow_variable_writes_run_scope_node_status",
            "workflow_run_id",
            "scope_run_id",
            "node_run_id",
            "status",
        ),
        Index("ix_workflow_variable_writes_attempt_status", "attempt_id", "status"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id")
    scope_run_id: UUID = Field(foreign_key="workflow_scope_runs.id")
    node_run_id: UUID = Field(foreign_key="workflow_node_runs.id")
    attempt_id: UUID = Field(foreign_key="workflow_node_attempts.id")
    name: str = Field(max_length=128)
    value: Any = Field(..., sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="staged", max_length=32)
    created_at: datetime = Field(default_factory=utcnow)
    committed_at: datetime | None = Field(default=None)


class WorkflowControlDecision(SQLModel, table=True):
    """One-time Agent control choice bound to its emitting Attempt."""

    __tablename__ = "workflow_control_decisions"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "target_node_run_id",
            "kind",
            name="uq_workflow_control_decision_target",
        ),
        UniqueConstraint("token", name="uq_workflow_control_decision_token"),
        Index("ix_workflow_control_decisions_attempt_status", "attempt_id", "status"),
        Index(
            "ix_workflow_control_decisions_target_status",
            "target_node_run_id",
            "status",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id")
    scope_run_id: UUID = Field(foreign_key="workflow_scope_runs.id")
    attempt_id: UUID = Field(foreign_key="workflow_node_attempts.id")
    target_node_run_id: UUID = Field(foreign_key="workflow_node_runs.id")
    kind: str = Field(max_length=32)
    token: str = Field(max_length=128)
    allowed_ports: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    value: Any | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    status: str = Field(default="pending", max_length=32)
    created_at: datetime = Field(default_factory=utcnow)
    committed_at: datetime | None = Field(default=None)


class WorkflowJob(SQLModel, table=True):
    __tablename__ = "workflow_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_workflow_job_dedupe"),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    scope_run_id: UUID | None = Field(default=None, index=True)
    node_run_id: UUID | None = Field(default=None, index=True)
    attempt_id: UUID | None = Field(default=None, index=True)
    job_type: str = Field(max_length=64, index=True)
    status: str = Field(default="queued", max_length=32, index=True)
    dedupe_key: str = Field(max_length=256)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    available_at: datetime = Field(default_factory=utcnow, index=True)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = Field(default=None)
    fencing_token: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowEvent(SQLModel, table=True):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "sequence", name="uq_workflow_event_sequence"
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    event_type: str = Field(max_length=128)
    data: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class WorkflowArtifact(SQLModel, table=True):
    __tablename__ = "workflow_artifacts"
    __table_args__ = (
        Index(
            "ix_workflow_artifacts_status_created_at",
            "status",
            "created_at",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    node_run_id: UUID | None = Field(default=None, index=True)
    created_by_attempt_id: UUID | None = Field(
        default=None, foreign_key="workflow_node_attempts.id", index=True
    )
    kind: str = Field(default="user", max_length=32)
    name: str = Field(max_length=512)
    uri: str = Field(max_length=2048, nullable=False, index=True)
    mime_type: str = Field(default="application/octet-stream", max_length=256)
    size_bytes: int = Field(default=0)
    sha256: str = Field(max_length=64, nullable=False)
    status: str = Field(default="available", max_length=32)
    created_at: datetime = Field(default_factory=utcnow)


class WorkflowArtifactGcCursor(SQLModel, table=True):
    """Durable progress cursor for bounded Artifact GC scans."""

    __tablename__ = "workflow_artifact_gc_cursors"

    cursor_key: str = Field(primary_key=True, max_length=128)
    offset: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowNodeConversation(SQLModel, table=True):
    """A durable, node-scoped Hermes conversation.

    Conversations intentionally do not reference ``WorkflowNodeAttempt`` or
    carry a workspace execution identity.  They use a stable Hermes session
    that is independent from business workflow runs.
    """

    __tablename__ = "workflow_node_conversations"
    __table_args__ = (
        UniqueConstraint(
            "remote_session_id", name="uq_workflow_node_conversation_session"
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    workflow_version_id: UUID = Field(foreign_key="workflow_versions.id", index=True)
    node_definition_id: str = Field(max_length=128)
    instance_id: str = Field(max_length=64, index=True)
    remote_session_id: str = Field(max_length=128, nullable=False)
    node_snapshot: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    status: str = Field(default="idle", max_length=32, index=True)
    event_seq: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    attention_reason: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowNodeConversationTurn(SQLModel, table=True):
    """One serialized user-to-agent turn within a node conversation."""

    __tablename__ = "workflow_node_conversation_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "turn_number",
            name="uq_workflow_node_conversation_turn_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "executor_instance_id",
            "external_run_id",
            name="uq_workflow_node_conversation_external_run",
        ),
        UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_workflow_node_conversation_turn_idempotency",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    conversation_id: UUID = Field(
        foreign_key="workflow_node_conversations.id", index=True
    )
    turn_number: int = Field(sa_column=Column(Integer, nullable=False))
    executor_instance_id: str = Field(max_length=64, index=True)
    user_message: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    assistant_message: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    idempotency_key: str | None = Field(default=None, max_length=128)
    status: str = Field(default="queued", max_length=32, index=True)
    external_run_id: str | None = Field(default=None, max_length=256, index=True)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2048)
    cancel_requested_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    cancel_requested_by: str | None = Field(default=None, max_length=128)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowNodeConversationEvent(SQLModel, table=True):
    """Replayable lifecycle event with a sequence scoped to one conversation."""

    __tablename__ = "workflow_node_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_workflow_node_conversation_event_sequence",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    conversation_id: UUID = Field(
        foreign_key="workflow_node_conversations.id", index=True
    )
    turn_id: UUID | None = Field(
        default=None, foreign_key="workflow_node_conversation_turns.id", index=True
    )
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    event_type: str = Field(max_length=128)
    data: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class WorkflowNodeConversationJob(SQLModel, table=True):
    """Durable external-operation job for a conversation turn."""

    __tablename__ = "workflow_node_conversation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dedupe_key", name="uq_workflow_node_conversation_job_dedupe"
        ),
        Index(
            "ix_workflow_node_conversation_jobs_claim",
            "status",
            "available_at",
        ),
    )

    id: UUID = Field(primary_key=True, default_factory=uuid4)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, max_length=64)
    conversation_id: UUID = Field(
        foreign_key="workflow_node_conversations.id", index=True
    )
    turn_id: UUID = Field(foreign_key="workflow_node_conversation_turns.id", index=True)
    job_type: str = Field(max_length=64, index=True)
    status: str = Field(default="queued", max_length=32, index=True)
    dedupe_key: str = Field(max_length=256)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    available_at: datetime = Field(default_factory=utcnow, index=True)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = Field(default=None)
    fencing_token: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    error_message: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

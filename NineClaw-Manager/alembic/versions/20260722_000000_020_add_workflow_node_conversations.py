"""Add durable independent Hermes node conversations.

Revision ID: 020
Revises: 019
Create Date: 2026-07-22 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_conversations",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id"),
            nullable=False,
        ),
        sa.Column(
            "workflow_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_versions.id"),
            nullable=False,
        ),
        sa.Column("node_definition_id", sa.String(length=128), nullable=False),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("remote_session_id", sa.String(length=128), nullable=False),
        sa.Column(
            "node_snapshot",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="idle"
        ),
        sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attention_reason", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "remote_session_id", name="uq_workflow_node_conversation_session"
        ),
    )
    op.create_index(
        "ix_workflow_node_conversations_tenant_id",
        "workflow_node_conversations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_node_conversations_workflow_id",
        "workflow_node_conversations",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_node_conversations_workflow_version_id",
        "workflow_node_conversations",
        ["workflow_version_id"],
    )
    op.create_index(
        "ix_workflow_node_conversations_instance_id",
        "workflow_node_conversations",
        ["instance_id"],
    )
    op.create_index(
        "ix_workflow_node_conversations_status",
        "workflow_node_conversations",
        ["status"],
    )

    op.create_table(
        "workflow_node_conversation_turns",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_conversations.id"),
            nullable=False,
        ),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("executor_instance_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_message",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("assistant_message", JSONB, nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="queued"
        ),
        sa.Column("external_run_id", sa.String(length=256), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_by", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "turn_number",
            name="uq_workflow_node_conversation_turn_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "executor_instance_id",
            "external_run_id",
            name="uq_workflow_node_conversation_external_run",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_workflow_node_conversation_turn_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_node_conversation_turns_tenant_id",
        "workflow_node_conversation_turns",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_turns_conversation_id",
        "workflow_node_conversation_turns",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_turns_executor_instance_id",
        "workflow_node_conversation_turns",
        ["executor_instance_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_turns_status",
        "workflow_node_conversation_turns",
        ["status"],
    )
    op.create_index(
        "ix_workflow_node_conversation_turns_external_run_id",
        "workflow_node_conversation_turns",
        ["external_run_id"],
    )

    op.create_table(
        "workflow_node_conversation_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_conversation_turns.id"),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_workflow_node_conversation_event_sequence",
        ),
    )
    op.create_index(
        "ix_workflow_node_conversation_events_tenant_id",
        "workflow_node_conversation_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_events_conversation_id",
        "workflow_node_conversation_events",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_events_turn_id",
        "workflow_node_conversation_events",
        ["turn_id"],
    )

    op.create_table(
        "workflow_node_conversation_jobs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_conversation_turns.id"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="queued"
        ),
        sa.Column("dedupe_key", sa.String(length=256), nullable=False),
        sa.Column(
            "payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_workflow_node_conversation_job_dedupe",
        ),
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_tenant_id",
        "workflow_node_conversation_jobs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_conversation_id",
        "workflow_node_conversation_jobs",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_turn_id",
        "workflow_node_conversation_jobs",
        ["turn_id"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_job_type",
        "workflow_node_conversation_jobs",
        ["job_type"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_status",
        "workflow_node_conversation_jobs",
        ["status"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_available_at",
        "workflow_node_conversation_jobs",
        ["available_at"],
    )
    op.create_index(
        "ix_workflow_node_conversation_jobs_claim",
        "workflow_node_conversation_jobs",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_table("workflow_node_conversation_jobs")
    op.drop_table("workflow_node_conversation_events")
    op.drop_table("workflow_node_conversation_turns")
    op.drop_table("workflow_node_conversations")

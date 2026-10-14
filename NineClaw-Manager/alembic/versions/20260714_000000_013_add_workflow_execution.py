"""Add durable Hermes agent workflow execution tables.

Revision ID: 013
Revises: 012
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UTC = sa.DateTime()


def _id_column(name: str = "id") -> sa.Column:
    return sa.Column(name, UUID(as_uuid=True), primary_key=True, nullable=False)


def upgrade() -> None:
    op.create_table(
        "workflows",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(2048), nullable=False, server_default=""),
        sa.Column(
            "draft_definition",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_version_number", sa.Integer(), nullable=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_workflows_tenant_name"),
    )
    op.create_index("ix_workflows_tenant_id", "workflows", ["tenant_id"])

    op.create_table(
        "workflow_versions",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflows.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("compiled_plan", JSONB, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_versions_number"
        ),
    )
    op.create_index(
        "ix_workflow_versions_tenant_id", "workflow_versions", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"]
    )

    op.create_table(
        "workflow_runs",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
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
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column(
            "input", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("output", JSONB, nullable=True),
        sa.Column(
            "budget", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested_at", UTC, nullable=True),
        sa.Column("cancel_requested_by", sa.String(128), nullable=True),
        sa.Column("attention_reason", sa.String(2048), nullable=True),
        sa.Column("started_at", UTC, nullable=True),
        sa.Column("finished_at", UTC, nullable=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
    )
    op.create_index("ix_workflow_runs_tenant_id", "workflow_runs", ["tenant_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index(
        "ix_workflow_runs_workflow_version_id", "workflow_runs", ["workflow_version_id"]
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_scope_runs",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("parent_scope_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("parent_node_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="root"),
        sa.Column("iteration_index", sa.Integer(), nullable=True),
        sa.Column(
            "state", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("finished_at", UTC, nullable=True),
        sa.UniqueConstraint(
            "parent_node_run_id", "iteration_index", name="uq_workflow_scope_iteration"
        ),
    )
    op.create_index(
        "ix_workflow_scope_runs_tenant_id", "workflow_scope_runs", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_scope_runs_workflow_run_id",
        "workflow_scope_runs",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_scope_runs_parent_scope_run_id",
        "workflow_scope_runs",
        ["parent_scope_run_id"],
    )
    op.create_index(
        "ix_workflow_scope_runs_parent_node_run_id",
        "workflow_scope_runs",
        ["parent_node_run_id"],
    )
    op.create_index("ix_workflow_scope_runs_status", "workflow_scope_runs", ["status"])

    op.create_table(
        "workflow_node_runs",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "scope_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_scope_runs.id"),
            nullable=False,
        ),
        sa.Column("node_definition_id", sa.String(128), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("input_snapshot", JSONB, nullable=True),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("active_attempt_id", UUID(as_uuid=True), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("finished_at", UTC, nullable=True),
        sa.UniqueConstraint(
            "workflow_run_id",
            "scope_run_id",
            "node_definition_id",
            name="uq_workflow_node_run",
        ),
    )
    op.create_index(
        "ix_workflow_node_runs_tenant_id", "workflow_node_runs", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_node_runs_workflow_run_id",
        "workflow_node_runs",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_node_runs_scope_run_id", "workflow_node_runs", ["scope_run_id"]
    )
    op.create_index("ix_workflow_node_runs_status", "workflow_node_runs", ["status"])
    op.create_index(
        "ix_workflow_node_runs_active_attempt_id",
        "workflow_node_runs",
        ["active_attempt_id"],
    )

    op.create_table(
        "workflow_edge_runs",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "scope_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_scope_runs.id"),
            nullable=False,
        ),
        sa.Column("edge_definition_id", sa.String(128), nullable=False),
        sa.Column("source_node_id", sa.String(128), nullable=False),
        sa.Column(
            "source_port", sa.String(128), nullable=False, server_default="default"
        ),
        sa.Column("target_node_id", sa.String(128), nullable=False),
        sa.Column(
            "target_port", sa.String(128), nullable=False, server_default="default"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("resolved_at", UTC, nullable=True),
        sa.UniqueConstraint(
            "workflow_run_id",
            "scope_run_id",
            "edge_definition_id",
            name="uq_workflow_edge_run",
        ),
    )
    op.create_index(
        "ix_workflow_edge_runs_tenant_id", "workflow_edge_runs", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_edge_runs_workflow_run_id",
        "workflow_edge_runs",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_edge_runs_scope_run_id", "workflow_edge_runs", ["scope_run_id"]
    )
    op.create_index("ix_workflow_edge_runs_status", "workflow_edge_runs", ["status"])

    op.create_table(
        "workflow_node_attempts",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "node_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_node_runs.id"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="prepared"),
        sa.Column("external_run_id", sa.String(256), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", UTC, nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("finished_at", UTC, nullable=True),
        sa.UniqueConstraint(
            "node_run_id", "generation", name="uq_workflow_attempt_generation"
        ),
    )
    op.create_index(
        "ix_workflow_node_attempts_tenant_id", "workflow_node_attempts", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_node_attempts_workflow_run_id",
        "workflow_node_attempts",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_node_attempts_node_run_id",
        "workflow_node_attempts",
        ["node_run_id"],
    )
    op.create_index(
        "ix_workflow_node_attempts_execution_id",
        "workflow_node_attempts",
        ["execution_id"],
    )
    op.create_index(
        "ix_workflow_node_attempts_status", "workflow_node_attempts", ["status"]
    )
    op.create_index(
        "ix_workflow_node_attempts_external_run_id",
        "workflow_node_attempts",
        ["external_run_id"],
    )

    op.create_table(
        "workflow_jobs",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("scope_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("node_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_id", UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("dedupe_key", sa.String(256), nullable=False),
        sa.Column(
            "payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("available_at", UTC, nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", UTC, nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_workflow_job_dedupe"),
    )
    op.create_index("ix_workflow_jobs_tenant_id", "workflow_jobs", ["tenant_id"])
    op.create_index(
        "ix_workflow_jobs_workflow_run_id", "workflow_jobs", ["workflow_run_id"]
    )
    op.create_index("ix_workflow_jobs_scope_run_id", "workflow_jobs", ["scope_run_id"])
    op.create_index("ix_workflow_jobs_node_run_id", "workflow_jobs", ["node_run_id"])
    op.create_index("ix_workflow_jobs_attempt_id", "workflow_jobs", ["attempt_id"])
    op.create_index("ix_workflow_jobs_job_type", "workflow_jobs", ["job_type"])
    op.create_index(
        "ix_workflow_jobs_status_available_at",
        "workflow_jobs",
        ["status", "available_at"],
    )

    op.create_table(
        "workflow_events",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "workflow_run_id", "sequence", name="uq_workflow_event_sequence"
        ),
    )
    op.create_index("ix_workflow_events_tenant_id", "workflow_events", ["tenant_id"])
    op.create_index(
        "ix_workflow_events_workflow_run_id", "workflow_events", ["workflow_run_id"]
    )

    op.create_table(
        "workflow_artifacts",
        _id_column(),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("node_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("uri", sa.String(2048), nullable=False),
        sa.Column(
            "mime_type",
            sa.String(256),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("created_at", UTC, nullable=False),
    )
    op.create_index(
        "ix_workflow_artifacts_tenant_id", "workflow_artifacts", ["tenant_id"]
    )
    op.create_index(
        "ix_workflow_artifacts_workflow_run_id",
        "workflow_artifacts",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_artifacts_node_run_id", "workflow_artifacts", ["node_run_id"]
    )


def downgrade() -> None:
    for table in (
        "workflow_artifacts",
        "workflow_events",
        "workflow_jobs",
        "workflow_node_attempts",
        "workflow_edge_runs",
        "workflow_node_runs",
        "workflow_scope_runs",
        "workflow_runs",
        "workflow_versions",
        "workflows",
    ):
        op.drop_table(table)

"""Artifact cleanup for Attempts that can no longer produce workflow output."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowArtifact, WorkflowNodeAttempt
from app.services.workflow.artifacts import ArtifactStoreError, artifact_store


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtifactCleanup:
    available_bytes: int = 0
    staged_bytes: int = 0


async def invalidate_attempt_artifacts(
    session: AsyncSession,
    *,
    attempt: WorkflowNodeAttempt,
    include_available: bool = True,
) -> ArtifactCleanup:
    """Delete staged/finalized artifacts from an invalid Attempt.

    Returns finalized and reserved-staging bytes removed from the Run budgets. A storage failure never
    leaves an artifact available: its metadata becomes ``cleanup_failed`` and
    Manager download endpoints reject every non-available Artifact.
    """
    statuses = (
        ("uploading", "staged", "available")
        if include_available
        else ("uploading", "staged")
    )
    artifacts = list(
        (
            await session.scalars(
                select(WorkflowArtifact).where(
                    WorkflowArtifact.created_by_attempt_id == attempt.id,
                    WorkflowArtifact.status.in_(statuses),
                )
            )
        ).all()
    )
    reclaimed_available_bytes = 0
    reclaimed_staged_bytes = 0
    for artifact in artifacts:
        try:
            if artifact.status in {"uploading", "staged"}:
                staged = artifact_store.restore_staged(
                    tenant_id=artifact.tenant_id,
                    workflow_run_id=artifact.workflow_run_id,
                    artifact_id=artifact.id,
                    name=artifact.name,
                    size_bytes=artifact.size_bytes,
                    sha256=artifact.sha256,
                    mime_type=artifact.mime_type,
                )
                await artifact_store.discard(staged)
            else:
                await artifact_store.delete(artifact.uri)
                reclaimed_available_bytes += artifact.size_bytes
        except ArtifactStoreError:
            artifact.status = "cleanup_failed"
            logger.warning(
                "workflow artifact cleanup failed: attempt=%s artifact=%s",
                attempt.id,
                artifact.id,
            )
        else:
            if artifact.status in {"uploading", "staged"}:
                reclaimed_staged_bytes += artifact.size_bytes
            await session.delete(artifact)
    return ArtifactCleanup(
        available_bytes=reclaimed_available_bytes,
        staged_bytes=reclaimed_staged_bytes,
    )

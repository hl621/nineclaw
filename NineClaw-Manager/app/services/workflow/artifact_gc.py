"""Conservative garbage collection for Manager-owned workflow Artifacts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.workflow import (
    WorkflowArtifact,
    WorkflowArtifactGcCursor,
    WorkflowNodeAttempt,
    WorkflowRun,
    utcnow,
)
from app.services.workflow.artifacts import (
    ArtifactStoreError,
    LocalArtifactStore,
    ManagedArtifactCandidate,
    MultipartUploadCandidate,
    S3ArtifactStore,
    artifact_store,
)


logger = logging.getLogger(__name__)

_TEMPORARY_ARTIFACT_STATUSES = {
    "uploading",
    "staged",
    "cleanup_failed",
    "cleanup_in_progress",
}
_ACTIVE_ATTEMPT_STATUSES = {"prepared", "dispatching", "dispatched"}


@dataclass(frozen=True)
class ArtifactGarbageCollectionResult:
    metadata_deleted: int = 0
    object_deleted: int = 0
    multipart_aborted: int = 0


@dataclass(frozen=True)
class ClaimedTemporaryArtifact:
    id: UUID
    tenant_id: str
    workflow_run_id: UUID
    name: str
    uri: str
    size_bytes: int
    sha256: str
    mime_type: str
    is_staging: bool


class ArtifactGarbageCollector:
    """Recover stale temporary metadata and storage objects after a crash.

    The collector deliberately keeps every DB reference and every candidate
    younger than the configured grace period.  Multiple Manager replicas can
    run it: temporary Artifact rows are claimed with ``SKIP LOCKED`` and
    storage deletes/aborts are idempotent.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        store: LocalArtifactStore | S3ArtifactStore | None = None,
    ) -> None:
        self._sessions = session_factory
        self._store = store or artifact_store
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if settings.workflow_artifact_gc_interval_seconds <= 0:
            logger.error("workflow artifact GC 间隔无效，已禁用")
            return
        if self._task is None and settings.workflow_artifact_gc_enabled:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="workflow-artifact-gc")

    async def close(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> ArtifactGarbageCollectionResult:
        grace_seconds = settings.workflow_artifact_gc_orphan_grace_seconds
        batch_size = settings.workflow_artifact_gc_batch_size
        max_pages = settings.workflow_artifact_gc_max_scan_pages
        if grace_seconds <= 0 or batch_size <= 0 or max_pages <= 0:
            logger.error("workflow artifact GC 配置无效")
            return ArtifactGarbageCollectionResult()
        cutoff = utcnow() - timedelta(seconds=grace_seconds)
        metadata_deleted = await self._collect_temporary_metadata(
            cutoff=cutoff, batch_size=batch_size
        )
        object_deleted = await self._collect_storage_candidates(
            cutoff=cutoff, batch_size=batch_size, max_pages=max_pages
        )
        multipart_aborted = 0
        if isinstance(self._store, S3ArtifactStore):
            multipart_aborted = await self._collect_multipart_uploads(
                cutoff=cutoff, batch_size=batch_size, max_pages=max_pages
            )
        return ArtifactGarbageCollectionResult(
            metadata_deleted=metadata_deleted,
            object_deleted=object_deleted,
            multipart_aborted=multipart_aborted,
        )

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("workflow artifact GC 执行失败")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=settings.workflow_artifact_gc_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def _collect_temporary_metadata(self, *, cutoff, batch_size: int) -> int:
        removed = 0
        seen_ids: set[UUID] = set()
        for _ in range(batch_size):
            claim = await self._claim_temporary_artifact(
                cutoff=cutoff, excluded_ids=seen_ids
            )
            if claim is None:
                return removed
            seen_ids.add(claim.id)
            try:
                if claim.is_staging:
                    staged = self._store.restore_staged(
                        tenant_id=claim.tenant_id,
                        workflow_run_id=claim.workflow_run_id,
                        artifact_id=claim.id,
                        name=claim.name,
                        size_bytes=claim.size_bytes,
                        sha256=claim.sha256,
                        mime_type=claim.mime_type,
                    )
                    await self._store.discard(staged)
                else:
                    await self._store.delete(claim.uri)
            except ArtifactStoreError:
                logger.warning("workflow artifact temporary cleanup failed")
                await self._finish_temporary_claim(claim, deleted=False)
            else:
                removed += int(await self._finish_temporary_claim(claim, deleted=True))
        return removed

    async def _claim_temporary_artifact(
        self, *, cutoff, excluded_ids: set[UUID]
    ) -> ClaimedTemporaryArtifact | None:
        """Claim one temporary Artifact without holding a DB transaction for I/O."""
        async with self._sessions() as session:
            artifact_conditions = [
                WorkflowArtifact.status.in_(_TEMPORARY_ARTIFACT_STATUSES),
                WorkflowArtifact.created_at <= cutoff,
                or_(
                    and_(
                        WorkflowArtifact.created_by_attempt_id.is_not(None),
                        WorkflowNodeAttempt.status.not_in(_ACTIVE_ATTEMPT_STATUSES),
                    ),
                    WorkflowArtifact.created_by_attempt_id.is_(None),
                ),
            ]
            if excluded_ids:
                artifact_conditions.append(WorkflowArtifact.id.not_in(excluded_ids))
            run = await session.scalar(
                select(WorkflowRun)
                .join(
                    WorkflowArtifact,
                    WorkflowArtifact.workflow_run_id == WorkflowRun.id,
                )
                .outerjoin(
                    WorkflowNodeAttempt,
                    WorkflowArtifact.created_by_attempt_id == WorkflowNodeAttempt.id,
                )
                .where(*artifact_conditions)
                .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                .with_for_update(skip_locked=True, of=WorkflowRun)
                .limit(1)
            )
            if run is None:
                return None
            artifact = await session.scalar(
                select(WorkflowArtifact)
                .outerjoin(
                    WorkflowNodeAttempt,
                    WorkflowArtifact.created_by_attempt_id == WorkflowNodeAttempt.id,
                )
                .where(
                    WorkflowArtifact.workflow_run_id == run.id,
                    *artifact_conditions,
                )
                .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                .with_for_update(skip_locked=True, of=WorkflowArtifact)
                .limit(1)
            )
            if artifact is None:
                return None
            is_staging = artifact.uri.startswith("staged://") or artifact.status in {
                "uploading",
                "staged",
            }
            claim = ClaimedTemporaryArtifact(
                id=artifact.id,
                tenant_id=artifact.tenant_id,
                workflow_run_id=artifact.workflow_run_id,
                name=artifact.name,
                uri=artifact.uri,
                size_bytes=artifact.size_bytes,
                sha256=artifact.sha256,
                mime_type=artifact.mime_type,
                is_staging=is_staging,
            )
            artifact.status = "cleanup_in_progress"
            await session.commit()
            return claim

    async def _finish_temporary_claim(
        self, claim: ClaimedTemporaryArtifact, *, deleted: bool
    ) -> bool:
        """Persist a storage cleanup outcome in a short Run-then-Artifact transaction."""
        async with self._sessions() as session:
            run = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.id == claim.workflow_run_id)
                .with_for_update()
            )
            artifact = await session.scalar(
                select(WorkflowArtifact)
                .where(
                    WorkflowArtifact.id == claim.id,
                    WorkflowArtifact.status == "cleanup_in_progress",
                )
                .with_for_update()
            )
            if run is None or artifact is None:
                return False
            if not deleted:
                artifact.status = "cleanup_failed"
                await session.commit()
                return False
            budget_key = (
                "artifact_staged_bytes" if claim.is_staging else "artifact_bytes"
            )
            run.budget = {
                **run.budget,
                budget_key: max(
                    0, int(run.budget.get(budget_key, 0)) - artifact.size_bytes
                ),
            }
            run.updated_at = utcnow()
            await session.delete(artifact)
            await session.commit()
            return True

    async def _cursor_offset(self, kind: str) -> int:
        async with self._sessions() as session:
            cursor = await session.get(WorkflowArtifactGcCursor, kind)
            return max(0, cursor.offset) if cursor is not None else 0

    async def _set_cursor_offset(self, kind: str, offset: int) -> None:
        async with self._sessions() as session:
            cursor = await session.scalar(
                select(WorkflowArtifactGcCursor)
                .where(WorkflowArtifactGcCursor.cursor_key == kind)
                .with_for_update()
            )
            if cursor is None:
                cursor = WorkflowArtifactGcCursor(
                    cursor_key=kind, offset=max(0, offset)
                )
                session.add(cursor)
            else:
                cursor.offset = max(0, offset)
                cursor.updated_at = utcnow()
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def _collect_storage_candidates(
        self, *, cutoff, batch_size: int, max_pages: int
    ) -> int:
        batch: list[ManagedArtifactCandidate] = []
        skipped = 0
        offset = await self._cursor_offset("storage")
        try:
            async for candidate in self._store.iter_expired_candidates(
                cutoff=cutoff, max_pages=max_pages
            ):
                if skipped < offset:
                    skipped += 1
                    continue
                batch.append(candidate)
                if len(batch) == batch_size:
                    deleted, retained = await self._delete_unreferenced_candidates(
                        batch
                    )
                    await self._set_cursor_offset("storage", offset + retained)
                    return deleted
            if batch:
                deleted, _ = await self._delete_unreferenced_candidates(batch)
                await self._set_cursor_offset("storage", 0)
                return deleted
            await self._set_cursor_offset("storage", 0)
        except ArtifactStoreError:
            logger.warning("workflow artifact storage candidate scan failed")
        return 0

    async def _delete_unreferenced_candidates(
        self, candidates: list[ManagedArtifactCandidate]
    ) -> tuple[int, int]:
        (
            protected_uris,
            protected_staging_ids,
            protected_final_ids,
        ) = await self._storage_references(candidates)
        deleted = 0
        retained = 0
        for candidate in candidates:
            if (
                candidate.uri in protected_uris
                or (
                    candidate.is_staging
                    and candidate.artifact_id in protected_staging_ids
                )
                or (
                    not candidate.is_staging
                    and candidate.artifact_id in protected_final_ids
                )
            ):
                retained += 1
                continue
            try:
                if await self._store.delete_expired_candidate(candidate):
                    deleted += 1
                else:
                    retained += 1
            except ArtifactStoreError:
                logger.warning("workflow artifact orphan cleanup failed")
                retained += 1
        return deleted, retained

    async def _collect_multipart_uploads(
        self, *, cutoff, batch_size: int, max_pages: int
    ) -> int:
        assert isinstance(self._store, S3ArtifactStore)
        batch: list[MultipartUploadCandidate] = []
        skipped = 0
        offset = await self._cursor_offset("multipart")
        try:
            async for candidate in self._store.iter_expired_multipart_uploads(
                cutoff=cutoff, max_pages=max_pages
            ):
                if skipped < offset:
                    skipped += 1
                    continue
                batch.append(candidate)
                if len(batch) == batch_size:
                    aborted, retained = (
                        await self._abort_unreferenced_multipart_uploads(batch)
                    )
                    await self._set_cursor_offset("multipart", offset + retained)
                    return aborted
            if batch:
                aborted, _ = await self._abort_unreferenced_multipart_uploads(batch)
                await self._set_cursor_offset("multipart", 0)
                return aborted
            await self._set_cursor_offset("multipart", 0)
        except ArtifactStoreError:
            logger.warning("workflow artifact multipart candidate scan failed")
        return 0

    async def _abort_unreferenced_multipart_uploads(
        self, candidates: list[MultipartUploadCandidate]
    ) -> tuple[int, int]:
        protected_ids = await self._artifact_ids(
            {candidate.artifact_id for candidate in candidates}
        )
        aborted = 0
        retained = 0
        for candidate in candidates:
            if candidate.artifact_id in protected_ids:
                retained += 1
                continue
            try:
                if await self._store.abort_expired_multipart_upload(candidate):
                    aborted += 1
                else:
                    retained += 1
            except ArtifactStoreError:
                logger.warning("workflow artifact multipart cleanup failed")
                retained += 1
        return aborted, retained

    async def _storage_references(
        self, candidates: list[ManagedArtifactCandidate]
    ) -> tuple[set[str], set[UUID], set[UUID]]:
        uris = {candidate.uri for candidate in candidates}
        artifact_ids = {candidate.artifact_id for candidate in candidates}
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        WorkflowArtifact.uri,
                        WorkflowArtifact.id,
                        WorkflowArtifact.status,
                    ).where(
                        or_(
                            WorkflowArtifact.uri.in_(uris),
                            WorkflowArtifact.id.in_(artifact_ids),
                        )
                    )
                )
            ).all()
        return (
            {uri for uri, _, _ in rows},
            {
                artifact_id
                for uri, artifact_id, status in rows
                if uri.startswith("staged://") or status in {"uploading", "staged"}
            },
            {
                artifact_id
                for _, artifact_id, status in rows
                if status in _TEMPORARY_ARTIFACT_STATUSES
            },
        )

    async def _artifact_ids(self, artifact_ids: set[UUID]) -> set[UUID]:
        async with self._sessions() as session:
            return set(
                (
                    await session.scalars(
                        select(WorkflowArtifact.id).where(
                            WorkflowArtifact.id.in_(artifact_ids)
                        )
                    )
                ).all()
            )

"""Crash-recovery tests for the workflow Artifact garbage collector."""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.workflow import (
    WorkflowArtifact,
    WorkflowNodeAttempt,
    WorkflowNodeRun,
    WorkflowRun,
    utcnow,
)
from app.services.workflow.artifact_gc import ArtifactGarbageCollector
from app.services.workflow.artifacts import (
    ArtifactStoreError,
    LocalArtifactStore,
    S3ArtifactStore,
)
from test_workflow_artifacts import _FakeS3Client
from test_workflow_runtime import (
    AGENT_NODE_ID,
    WORKFLOW_TEST_DATABASE_URL,
    _create_run,
    _linear_definition,
    workflow_sessions,
)


pytestmark = pytest.mark.skipif(
    not WORKFLOW_TEST_DATABASE_URL,
    reason="需要 WORKFLOW_TEST_DATABASE_URL 指向已迁移的 PostgreSQL",
)


class _FailingDiscardStore(LocalArtifactStore):
    def __init__(self, root) -> None:
        super().__init__(root)
        self.discard_calls = 0

    async def discard(self, staged) -> None:
        del staged
        self.discard_calls += 1
        raise ArtifactStoreError("simulated cleanup failure")


async def _stage_artifact(
    workflow_sessions,
    store: LocalArtifactStore,
    *,
    status: str = "staged",
) -> tuple[str, UUID, UUID]:
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    artifact_id = uuid4()
    staged = await store.stage_stream(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="stale.txt",
        chunks=_chunks(b"stale"),
    )
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        run.status = "succeeded"
        run.budget = {"artifact_staged_bytes": staged.size_bytes}
        session.add(
            WorkflowArtifact(
                id=artifact_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                name="stale.txt",
                uri=f"staged://{artifact_id}",
                mime_type=staged.mime_type,
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                status=status,
                created_at=utcnow() - timedelta(days=2),
            )
        )
        await session.commit()
    return tenant_id, run_id, artifact_id


@pytest.mark.asyncio
async def test_gc_reclaims_stale_staged_metadata_and_budget(
    workflow_sessions, tmp_path
):
    store = LocalArtifactStore(tmp_path)
    _, run_id, artifact_id = await _stage_artifact(workflow_sessions, store)

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.metadata_deleted == 1
    async with workflow_sessions() as session:
        assert await session.get(WorkflowArtifact, artifact_id) is None
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.budget["artifact_staged_bytes"] == 0
    assert list(tmp_path.rglob("*.staged-*")) == []


@pytest.mark.asyncio
async def test_gc_deletes_finalize_orphan_and_preserves_referenced_file(
    workflow_sessions, tmp_path
):
    store = LocalArtifactStore(tmp_path)
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    orphan_id = uuid4()
    referenced_id = uuid4()
    orphan_uri, _, _, _ = await store.put_bytes(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=orphan_id,
        name="orphan.txt",
        content=b"orphan",
    )
    referenced_uri, size, digest, mime_type = await store.put_bytes(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=referenced_id,
        name="referenced.txt",
        content=b"referenced",
    )
    orphan_path = await store.file_path(orphan_uri)
    referenced_path = await store.file_path(referenced_uri)
    old_at = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(orphan_path, (old_at, old_at))
    os.utime(referenced_path, (old_at, old_at))
    async with workflow_sessions() as session:
        session.add(
            WorkflowArtifact(
                id=referenced_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                name="referenced.txt",
                uri=referenced_uri,
                mime_type=mime_type,
                size_bytes=size,
                sha256=digest,
                status="available",
                created_at=utcnow() - timedelta(days=2),
            )
        )
        await session.commit()

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.object_deleted == 1
    assert not orphan_path.exists()
    assert referenced_path.exists()


@pytest.mark.asyncio
async def test_gc_retries_failed_cleanup_once_per_cycle(workflow_sessions, tmp_path):
    store = _FailingDiscardStore(tmp_path)
    _, _, artifact_id = await _stage_artifact(
        workflow_sessions, store, status="cleanup_failed"
    )

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.metadata_deleted == 0
    assert store.discard_calls == 1
    async with workflow_sessions() as session:
        artifact = await session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        assert artifact.status == "cleanup_failed"


@pytest.mark.asyncio
async def test_gc_deletes_s3_orphan_and_aborts_old_multipart(
    workflow_sessions, tmp_path
):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    artifact_id = uuid4()
    uri, _, _, _ = await store.put_bytes(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="orphan.txt",
        content=b"orphan",
    )
    key = uri.removeprefix("s3://workflow-test/")
    old = utcnow() - timedelta(days=2)
    client.object_times[("workflow-test", key)] = old
    client.multipart_uploads.append(
        {
            "Bucket": "workflow-test",
            "Key": key,
            "UploadId": "orphan-upload",
            "Initiated": old,
        }
    )

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.object_deleted == 1
    assert result.multipart_aborted == 1
    assert client.objects == {}
    assert client.multipart_uploads == []


@pytest.mark.asyncio
async def test_gc_removes_stale_s3_local_staging_after_finalize(
    workflow_sessions, tmp_path
):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    artifact_id = uuid4()
    staged = await store.stage_stream(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="available.txt",
        chunks=_chunks(b"available"),
    )
    key = store._key(staged.relative)
    client.upload_file(
        str(staged.staging),
        "workflow-test",
        key,
        ExtraArgs={"ContentType": staged.mime_type},
    )
    old = utcnow() - timedelta(days=2)
    client.object_times[("workflow-test", key)] = old
    old_at = old.timestamp()
    os.utime(staged.staging, (old_at, old_at))
    async with workflow_sessions() as session:
        session.add(
            WorkflowArtifact(
                id=artifact_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                name="available.txt",
                uri=f"s3://workflow-test/{key}",
                mime_type=staged.mime_type,
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                status="available",
            )
        )
        await session.commit()

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.object_deleted == 1
    assert not staged.staging.exists()
    assert ("workflow-test", key) in client.objects


@pytest.mark.asyncio
async def test_gc_keeps_finalized_object_while_active_attempt_has_staged_metadata(
    workflow_sessions, tmp_path
):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    artifact_id = uuid4()
    staged = await store.stage_stream(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="pending.txt",
        chunks=_chunks(b"pending"),
    )
    key = store._key(staged.relative)
    client.upload_file(
        str(staged.staging),
        "workflow-test",
        key,
        ExtraArgs={"ContentType": staged.mime_type},
    )
    old = utcnow() - timedelta(days=2)
    client.object_times[("workflow-test", key)] = old
    async with workflow_sessions() as session:
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert node is not None
        attempt = WorkflowNodeAttempt(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            node_run_id=node.id,
            generation=0,
            execution_id=f"gc-active-{uuid4().hex}",
            status="dispatched",
        )
        session.add(attempt)
        await session.flush()
        session.add(
            WorkflowArtifact(
                id=artifact_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                created_by_attempt_id=attempt.id,
                name="pending.txt",
                uri=f"staged://{artifact_id}",
                mime_type=staged.mime_type,
                size_bytes=staged.size_bytes,
                sha256=staged.sha256,
                status="staged",
                created_at=old,
            )
        )
        await session.commit()

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.object_deleted == 0
    assert ("workflow-test", key) in client.objects


@pytest.mark.asyncio
async def test_gc_reclaims_stale_manual_upload_with_failed_attempt_artifact(
    workflow_sessions, tmp_path
):
    store = LocalArtifactStore(tmp_path)
    instance_id = f"agent-{uuid4().hex[:16]}"
    tenant_id, run_id, _ = await _create_run(
        workflow_sessions,
        _linear_definition(instance_id=instance_id),
        with_instance=True,
    )
    manual_id = uuid4()
    attempt_artifact_id = uuid4()
    manual_staged = await store.stage_stream(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=manual_id,
        name="manual.txt",
        chunks=_chunks(b"manual"),
    )
    attempt_staged = await store.stage_stream(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=attempt_artifact_id,
        name="attempt.txt",
        chunks=_chunks(b"attempt"),
    )
    old = utcnow() - timedelta(days=2)
    async with workflow_sessions() as session:
        run = await session.get(WorkflowRun, run_id)
        node = await session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_definition_id == AGENT_NODE_ID,
            )
        )
        assert run is not None and node is not None
        run.status = "running"
        run.budget = {
            "artifact_staged_bytes": manual_staged.size_bytes
            + attempt_staged.size_bytes
        }
        attempt = WorkflowNodeAttempt(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            node_run_id=node.id,
            generation=0,
            execution_id=f"gc-test-{uuid4().hex}",
            status="failed",
        )
        session.add(attempt)
        await session.flush()
        session.add_all(
            [
                WorkflowArtifact(
                    id=manual_id,
                    tenant_id=tenant_id,
                    workflow_run_id=run_id,
                    name="manual.txt",
                    uri=f"staged://{manual_id}",
                    mime_type=manual_staged.mime_type,
                    size_bytes=manual_staged.size_bytes,
                    sha256=manual_staged.sha256,
                    status="uploading",
                    created_at=old - timedelta(seconds=1),
                ),
                WorkflowArtifact(
                    id=attempt_artifact_id,
                    tenant_id=tenant_id,
                    workflow_run_id=run_id,
                    created_by_attempt_id=attempt.id,
                    name="attempt.txt",
                    uri=f"staged://{attempt_artifact_id}",
                    mime_type=attempt_staged.mime_type,
                    size_bytes=attempt_staged.size_bytes,
                    sha256=attempt_staged.sha256,
                    status="staged",
                    created_at=old,
                ),
            ]
        )
        await session.commit()

    result = await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()

    assert result.metadata_deleted == 2
    async with workflow_sessions() as session:
        assert await session.get(WorkflowArtifact, manual_id) is None
        assert await session.get(WorkflowArtifact, attempt_artifact_id) is None
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.budget["artifact_staged_bytes"] == 0
    assert not manual_staged.staging.exists()
    assert not attempt_staged.staging.exists()


@pytest.mark.asyncio
async def test_gc_limits_each_storage_pass_to_configured_batch(
    workflow_sessions, tmp_path, monkeypatch
):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    old = utcnow() - timedelta(days=2)
    for index in range(3):
        uri, _, _, _ = await store.put_bytes(
            tenant_id=tenant_id,
            workflow_run_id=run_id,
            artifact_id=uuid4(),
            name=f"orphan-{index}.txt",
            content=b"orphan",
        )
        client.object_times[
            ("workflow-test", uri.removeprefix("s3://workflow-test/"))
        ] = old
    monkeypatch.setattr(settings, "workflow_artifact_gc_batch_size", 1)
    collector = ArtifactGarbageCollector(workflow_sessions, store=store)

    assert (await collector.run_once()).object_deleted == 1
    assert len(client.objects) == 2
    assert (await collector.run_once()).object_deleted == 1
    assert len(client.objects) == 1
    assert (await collector.run_once()).object_deleted == 1
    assert client.objects == {}


@pytest.mark.asyncio
async def test_gc_persists_storage_offset_across_collector_restart(
    workflow_sessions, tmp_path, monkeypatch
):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    tenant_id, run_id, _ = await _create_run(workflow_sessions, _linear_definition())
    protected_id = UUID("00000000-0000-0000-0000-000000000001")
    orphan_id = UUID("00000000-0000-0000-0000-000000000002")
    protected_uri, size, digest, mime_type = await store.put_bytes(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=protected_id,
        name="protected.txt",
        content=b"protected",
    )
    orphan_uri, _, _, _ = await store.put_bytes(
        tenant_id=tenant_id,
        workflow_run_id=run_id,
        artifact_id=orphan_id,
        name="orphan.txt",
        content=b"orphan",
    )
    old = utcnow() - timedelta(days=2)
    for uri in (protected_uri, orphan_uri):
        client.object_times[
            ("workflow-test", uri.removeprefix("s3://workflow-test/"))
        ] = old
    async with workflow_sessions() as session:
        session.add(
            WorkflowArtifact(
                id=protected_id,
                tenant_id=tenant_id,
                workflow_run_id=run_id,
                name="protected.txt",
                uri=protected_uri,
                mime_type=mime_type,
                size_bytes=size,
                sha256=digest,
                status="available",
            )
        )
        await session.commit()
    monkeypatch.setattr(settings, "workflow_artifact_gc_batch_size", 1)

    assert (
        await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()
    ).object_deleted == 0
    assert (
        "workflow-test",
        orphan_uri.removeprefix("s3://workflow-test/"),
    ) in client.objects
    assert (
        await ArtifactGarbageCollector(workflow_sessions, store=store).run_once()
    ).object_deleted == 1
    assert (
        "workflow-test",
        orphan_uri.removeprefix("s3://workflow-test/"),
    ) not in client.objects


async def _chunks(content: bytes):
    yield content

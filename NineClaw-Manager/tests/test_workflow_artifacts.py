"""Tests for the Manager-owned local workflow artifact store."""

import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.workflow.artifacts import (
    ArtifactStoreError,
    LocalArtifactStore,
    S3ArtifactStore,
)


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.object_times: dict[tuple[str, str], datetime] = {}
        self.multipart_uploads: list[dict[str, object]] = []
        self.page_size = 100

    def upload_file(
        self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, str]
    ) -> None:
        del ExtraArgs
        self.objects[(bucket, key)] = Path(filename).read_bytes()
        self.object_times[(bucket, key)] = datetime.now(timezone.utc)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, BytesIO]:
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)
        self.object_times.pop((Bucket, Key), None)

    def list_objects_v2(self, **kwargs: str) -> dict[str, object]:
        bucket = kwargs["Bucket"]
        prefix = kwargs["Prefix"]
        entries = sorted(
            (key, self.object_times[(stored_bucket, key)])
            for stored_bucket, key in self.objects
            if stored_bucket == bucket and key.startswith(prefix)
        )
        start = int(kwargs.get("ContinuationToken", "0"))
        page = entries[start : start + self.page_size]
        next_start = start + len(page)
        response: dict[str, object] = {
            "Contents": [
                {"Key": key, "LastModified": modified_at} for key, modified_at in page
            ],
            "IsTruncated": next_start < len(entries),
        }
        if next_start < len(entries):
            response["NextContinuationToken"] = str(next_start)
        return response

    def list_multipart_uploads(self, **kwargs: str) -> dict[str, object]:
        bucket = kwargs["Bucket"]
        prefix = kwargs["Prefix"]
        entries = sorted(
            (
                upload
                for upload in self.multipart_uploads
                if upload["Bucket"] == bucket
                and isinstance(upload["Key"], str)
                and upload["Key"].startswith(prefix)
            ),
            key=lambda upload: (str(upload["Key"]), str(upload["UploadId"])),
        )
        key_marker = kwargs.get("KeyMarker")
        upload_marker = kwargs.get("UploadIdMarker")
        if key_marker is not None:
            entries = [
                upload
                for upload in entries
                if (str(upload["Key"]), str(upload["UploadId"]))
                > (key_marker, upload_marker or "")
            ]
        page = entries[: self.page_size]
        response: dict[str, object] = {
            "Uploads": [
                {
                    "Key": upload["Key"],
                    "UploadId": upload["UploadId"],
                    "Initiated": upload["Initiated"],
                }
                for upload in page
            ],
            "IsTruncated": len(entries) > len(page),
        }
        if len(entries) > len(page):
            response["NextKeyMarker"] = page[-1]["Key"]
            response["NextUploadIdMarker"] = page[-1]["UploadId"]
        return response

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> None:
        self.multipart_uploads = [
            upload
            for upload in self.multipart_uploads
            if (upload["Bucket"], upload["Key"], upload["UploadId"])
            != (Bucket, Key, UploadId)
        ]


@pytest.mark.asyncio
async def test_local_artifact_store_round_trip_and_blocks_path_escape(tmp_path):
    store = LocalArtifactStore(tmp_path)
    run_id = uuid4()
    artifact_id = uuid4()

    uri, size, digest, mime_type = await store.put_bytes(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="../report.txt",
        content=b"workflow artifact",
    )

    assert size == len(b"workflow artifact")
    assert len(digest) == 64
    assert mime_type == "text/plain"
    assert uri.endswith("/report.txt")
    assert await store.read_bytes(uri) == b"workflow artifact"
    with pytest.raises(ArtifactStoreError):
        await store.read_bytes("local://../../etc/passwd")


@pytest.mark.asyncio
async def test_local_artifact_store_hashes_untrusted_tenant_path_and_bounds_stream(
    tmp_path,
):
    store = LocalArtifactStore(tmp_path)
    run_id = uuid4()
    artifact_id = uuid4()

    async def chunks():
        yield b"ab"
        yield b"cd"

    with pytest.raises(ArtifactStoreError):
        await store.put_stream(
            tenant_id="../../outside",
            workflow_run_id=run_id,
            artifact_id=artifact_id,
            name="report.txt",
            chunks=chunks(),
            max_bytes=3,
        )

    async def valid_chunks():
        yield b"ab"
        yield b"cd"

    uri, size, _, _ = await store.put_stream(
        tenant_id="../../outside",
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="report.txt",
        chunks=valid_chunks(),
        max_bytes=4,
    )

    assert ".." not in uri
    assert size == 4
    assert await store.read_bytes(uri) == b"abcd"
    assert all(path.is_relative_to(tmp_path) for path in tmp_path.rglob("*"))


@pytest.mark.asyncio
async def test_s3_artifact_store_stages_streams_and_hides_object_path(tmp_path):
    client = _FakeS3Client()
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    run_id = uuid4()
    artifact_id = uuid4()

    async def chunks():
        yield b"manager "
        yield b"owned"

    staged = await store.stage_stream(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="result.txt",
        chunks=chunks(),
    )
    restored = store.restore_staged(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=artifact_id,
        name="result.txt",
        size_bytes=staged.size_bytes,
        sha256=staged.sha256,
        mime_type=staged.mime_type,
    )
    uri, size, digest, mime_type = await store.finalize(restored)

    assert uri.startswith("s3://workflow-test/manager-only/")
    assert "tenant-a" not in uri
    assert (size, digest, mime_type) == (
        len(b"manager owned"),
        staged.sha256,
        "text/plain",
    )
    assert await store.read_bytes(uri) == b"manager owned"
    await store.delete(uri)
    assert client.objects == {}


@pytest.mark.asyncio
async def test_local_store_enumerates_and_deletes_only_old_managed_candidates(tmp_path):
    store = LocalArtifactStore(tmp_path)
    run_id = uuid4()
    old_artifact_id = uuid4()
    staged_artifact_id = uuid4()
    fresh_artifact_id = uuid4()

    old_uri, _, _, _ = await store.put_bytes(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=old_artifact_id,
        name="old.txt",
        content=b"old",
    )
    staged = await store.stage_stream(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=staged_artifact_id,
        name="staged.txt",
        chunks=_chunks(b"staged"),
    )
    await store.put_bytes(
        tenant_id="tenant-a",
        workflow_run_id=run_id,
        artifact_id=fresh_artifact_id,
        name="fresh.txt",
        content=b"fresh",
    )
    old_path = await store.file_path(old_uri)
    old_at = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    os.utime(old_path, (old_at, old_at))
    os.utime(staged.staging, (old_at, old_at))
    (tmp_path / "unmanaged.txt").write_bytes(b"keep")

    candidates = [
        candidate
        async for candidate in store.iter_expired_candidates(
            cutoff=datetime.now(timezone.utc) - timedelta(days=1)
        )
    ]

    assert {candidate.artifact_id for candidate in candidates} == {
        old_artifact_id,
        staged_artifact_id,
    }
    assert any(candidate.is_staging for candidate in candidates)
    for candidate in candidates:
        assert await store.delete_expired_candidate(candidate)
    assert not old_path.exists()
    assert not staged.staging.exists()
    assert (tmp_path / "unmanaged.txt").exists()


@pytest.mark.asyncio
async def test_s3_store_paginates_managed_orphans_and_aborts_multipart(tmp_path):
    client = _FakeS3Client()
    client.page_size = 1
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=client,
    )
    run_id = uuid4()
    artifact_ids = [uuid4(), uuid4()]
    uris: list[str] = []
    for artifact_id in artifact_ids:
        uri, _, _, _ = await store.put_bytes(
            tenant_id="tenant-a",
            workflow_run_id=run_id,
            artifact_id=artifact_id,
            name=f"{artifact_id}.txt",
            content=b"orphan",
        )
        uris.append(uri)
    old = datetime.now(timezone.utc) - timedelta(days=2)
    for uri in uris:
        key = uri.removeprefix("s3://workflow-test/")
        client.object_times[("workflow-test", key)] = old
    old_key = uris[0].removeprefix("s3://workflow-test/")
    client.multipart_uploads.extend(
        [
            {
                "Bucket": "workflow-test",
                "Key": old_key,
                "UploadId": "old-upload",
                "Initiated": old,
            },
            {
                "Bucket": "workflow-test",
                "Key": old_key,
                "UploadId": "fresh-upload",
                "Initiated": datetime.now(timezone.utc),
            },
        ]
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    candidates = [
        candidate async for candidate in store.iter_expired_candidates(cutoff=cutoff)
    ]
    assert {candidate.uri for candidate in candidates} == set(uris)
    for candidate in candidates:
        assert await store.delete_expired_candidate(candidate)
    uploads = [
        candidate
        async for candidate in store.iter_expired_multipart_uploads(cutoff=cutoff)
    ]
    assert [candidate.upload_id for candidate in uploads] == ["old-upload"]
    assert await store.abort_expired_multipart_upload(uploads[0])
    assert [upload["UploadId"] for upload in client.multipart_uploads] == [
        "fresh-upload"
    ]


@pytest.mark.asyncio
async def test_s3_store_refuses_gc_scan_without_prefix(tmp_path):
    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="",
        staging_root=tmp_path,
        client=_FakeS3Client(),
    )

    with pytest.raises(ArtifactStoreError):
        _ = [
            candidate
            async for candidate in store.iter_expired_candidates(
                cutoff=datetime.now(timezone.utc)
            )
        ]


@pytest.mark.asyncio
async def test_s3_store_rejects_repeated_object_and_multipart_cursors(tmp_path):
    class LoopingClient(_FakeS3Client):
        def __init__(self) -> None:
            super().__init__()
            self.object_calls = 0
            self.multipart_calls = 0

        def list_objects_v2(self, **kwargs: str) -> dict[str, object]:
            del kwargs
            tokens = ["first", "second", "first"]
            token = tokens[min(self.object_calls, len(tokens) - 1)]
            self.object_calls += 1
            return {"Contents": [], "IsTruncated": True, "NextContinuationToken": token}

        def list_multipart_uploads(self, **kwargs: str) -> dict[str, object]:
            del kwargs
            markers = [("first", "one"), ("second", "two"), ("first", "one")]
            key, upload_id = markers[min(self.multipart_calls, len(markers) - 1)]
            self.multipart_calls += 1
            return {
                "Uploads": [],
                "IsTruncated": True,
                "NextKeyMarker": key,
                "NextUploadIdMarker": upload_id,
            }

    store = S3ArtifactStore(
        bucket="workflow-test",
        prefix="manager-only",
        staging_root=tmp_path,
        client=LoopingClient(),
    )

    with pytest.raises(ArtifactStoreError):
        _ = [
            candidate
            async for candidate in store.iter_expired_candidates(
                cutoff=datetime.now(timezone.utc)
            )
        ]
    with pytest.raises(ArtifactStoreError):
        _ = [
            candidate
            async for candidate in store.iter_expired_multipart_uploads(
                cutoff=datetime.now(timezone.utc)
            )
        ]


async def _chunks(content: bytes):
    yield content

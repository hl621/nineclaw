"""Manager-owned workflow Artifact stores.

Hermes never receives a URI, object key, bucket name or storage credential.
Both backends stage request streams on Manager-owned local disk, then make an
artifact available only after the caller records its finalized metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from uuid import UUID

from app.core.config import settings


class ArtifactStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedArtifact:
    target: Path
    staging: Path
    relative: Path
    size_bytes: int
    sha256: str
    mime_type: str


@dataclass(frozen=True)
class ManagedArtifactCandidate:
    """An expired file/object in a Manager-owned Artifact location.

    ``uri`` stays internal to Manager.  It is used only to compare a storage
    candidate against persisted Artifact metadata before deletion.
    """

    uri: str
    artifact_id: UUID
    is_staging: bool
    modified_at: datetime
    local_relative: Path | None = None


@dataclass(frozen=True)
class MultipartUploadCandidate:
    """An expired S3 multipart upload under the Manager-owned prefix."""

    key: str
    artifact_id: UUID
    upload_id: str
    initiated_at: datetime


_TENANT_SEGMENT_RE = re.compile(r"[0-9a-f]{64}")


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _next_or_none(iterator: object) -> object | None:
    try:
        return next(iterator)  # type: ignore[arg-type]
    except StopIteration:
        return None


class LocalArtifactStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root or settings.workflow_artifact_storage_path).resolve()

    async def put_bytes(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> tuple[str, int, str, str]:
        async def chunks() -> AsyncIterator[bytes]:
            yield content

        return await self.put_stream(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            name=name,
            chunks=chunks(),
            mime_type=mime_type,
        )

    async def put_stream(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        chunks: AsyncIterator[bytes],
        mime_type: str | None = None,
        max_bytes: int | None = None,
    ) -> tuple[str, int, str, str]:
        staged = await self.stage_stream(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            name=name,
            chunks=chunks,
            mime_type=mime_type,
            max_bytes=max_bytes,
        )
        try:
            return await self.finalize(staged)
        except BaseException:
            await self.discard(staged)
            raise

    async def stage_stream(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        chunks: AsyncIterator[bytes],
        mime_type: str | None = None,
        max_bytes: int | None = None,
    ) -> StagedArtifact:
        """Write a bounded stream without exposing it as an Artifact yet."""
        effective_limit = min(
            settings.workflow_artifact_max_upload_size,
            (
                max_bytes
                if max_bytes is not None
                else settings.workflow_artifact_max_upload_size
            ),
        )
        if effective_limit < 0:
            raise ArtifactStoreError("产物大小限制无效")
        safe_name = self._safe_name(name)
        relative = self._relative_path(
            tenant_id, workflow_run_id, artifact_id, safe_name
        )
        target = (self._root / relative).resolve()
        self._ensure_within_root(target)
        # The artifact ID is already unguessable and unique.  A deterministic
        # staging location lets the separate workspace commit request restore
        # its staged stream without persisting a local filesystem path in DB.
        staging = target.with_name(f".{target.name}.staged-{artifact_id}")
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size_bytes = 0
        handle = await asyncio.to_thread(staging.open, "wb")
        try:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ArtifactStoreError("产物流包含非字节数据")
                size_bytes += len(chunk)
                if size_bytes > effective_limit:
                    raise ArtifactStoreError("产物超过最大大小限制")
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
            await asyncio.to_thread(handle.close)
            handle = None
        except BaseException:
            if handle is not None:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(staging.unlink, missing_ok=True)
            raise
        resolved_mime = (
            mime_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        return StagedArtifact(
            target=target,
            staging=staging,
            relative=relative,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
            mime_type=resolved_mime,
        )

    async def finalize(self, staged: StagedArtifact) -> tuple[str, int, str, str]:
        self._ensure_within_root(staged.target)
        self._ensure_within_root(staged.staging)
        try:
            await asyncio.to_thread(os.replace, staged.staging, staged.target)
        except OSError as exc:
            raise ArtifactStoreError("产物文件落盘失败") from exc
        return (
            f"local://{staged.relative.as_posix()}",
            staged.size_bytes,
            staged.sha256,
            staged.mime_type,
        )

    async def discard(self, staged: StagedArtifact) -> None:
        self._ensure_within_root(staged.staging)
        try:
            await asyncio.to_thread(staged.staging.unlink, missing_ok=True)
        except OSError as exc:
            raise ArtifactStoreError("产物暂存文件删除失败") from exc

    async def read_bytes(self, uri: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream_bytes(uri)])

    async def stream_bytes(self, uri: str) -> AsyncIterator[bytes]:
        path = await self.file_path(uri)
        handle = None
        try:
            handle = await asyncio.to_thread(path.open, "rb")
            while chunk := await asyncio.to_thread(handle.read, 64 * 1024):
                yield chunk
        except OSError as exc:
            raise ArtifactStoreError("产物文件不存在或不可读取") from exc
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)

    def restore_staged(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        size_bytes: int,
        sha256: str,
        mime_type: str,
    ) -> StagedArtifact:
        safe_name = self._safe_name(name)
        relative = self._relative_path(
            tenant_id, workflow_run_id, artifact_id, safe_name
        )
        target = (self._root / relative).resolve()
        self._ensure_within_root(target)
        return StagedArtifact(
            target=target,
            staging=target.with_name(f".{target.name}.staged-{artifact_id}"),
            relative=relative,
            size_bytes=size_bytes,
            sha256=sha256,
            mime_type=mime_type,
        )

    async def file_path(self, uri: str) -> Path:
        path = self._path_for_uri(uri)
        try:
            stat = await asyncio.to_thread(path.stat)
        except OSError as exc:
            raise ArtifactStoreError("产物文件不存在或不可读取") from exc
        if not path.is_file() or stat.st_size < 0:
            raise ArtifactStoreError("产物文件不存在或不可读取")
        return path

    async def delete(self, uri: str) -> None:
        path = self._path_for_uri(uri)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise ArtifactStoreError("产物文件删除失败") from exc

    async def iter_expired_candidates(
        self, *, cutoff: datetime, max_pages: int | None = None
    ) -> AsyncIterator[ManagedArtifactCandidate]:
        """Yield only old, regular files in the fixed Artifact layout.

        The scan never follows symbolic links and ignores files outside the
        hashed-tenant/run/artifact/name layout.  Metadata references are
        checked by the garbage collector before any yielded candidate is
        deleted.
        """
        del max_pages
        iterator = self._iter_expired_candidates(_utc_naive(cutoff))
        while (
            candidate := await asyncio.to_thread(_next_or_none, iterator)
        ) is not None:
            yield candidate  # type: ignore[misc]

    async def delete_expired_candidate(
        self, candidate: ManagedArtifactCandidate
    ) -> bool:
        """Delete a previously scanned local candidate if it is unchanged.

        Revalidating the managed path and modification time closes races with
        filesystem changes between scanning and deletion.
        """
        if candidate.local_relative is None or not candidate.uri.startswith("local://"):
            raise ArtifactStoreError("非法本地产物候选")
        parsed = self._parse_managed_relative(candidate.local_relative)
        if parsed is None or parsed != (candidate.artifact_id, candidate.is_staging):
            raise ArtifactStoreError("非法本地产物路径")
        path = self._root / candidate.local_relative
        try:
            resolved = path.resolve(strict=True)
            self._ensure_within_root(resolved)
            stat = await asyncio.to_thread(path.lstat)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ArtifactStoreError("产物候选检查失败") from exc
        if path.is_symlink() or not S_ISREG(stat.st_mode):
            return False
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        if _utc_naive(modified_at) != _utc_naive(candidate.modified_at):
            return False
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ArtifactStoreError("产物文件删除失败") from exc
        return True

    def _path_for_uri(self, uri: str) -> Path:
        if not uri.startswith("local://"):
            raise ArtifactStoreError("不支持的产物 URI")
        candidate = (self._root / uri.removeprefix("local://")).resolve()
        self._ensure_within_root(candidate)
        return candidate

    def _relative_path(
        self,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
    ) -> Path:
        tenant_segment = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
        return Path(tenant_segment) / str(workflow_run_id) / str(artifact_id) / name

    def _iter_expired_candidates(
        self, cutoff: datetime
    ) -> AsyncIterator[ManagedArtifactCandidate]:
        # This is a synchronous generator despite the AsyncIterator annotation
        # at the public boundary.  Filesystem iteration runs in a worker thread
        # one item at a time so large roots are not loaded into memory.
        if not self._root.exists():
            return
        cutoff = _utc_naive(cutoff)
        for directory, child_directories, filenames in os.walk(
            self._root, followlinks=False
        ):
            directory_path = Path(directory)
            child_directories[:] = sorted(
                child
                for child in child_directories
                if not (directory_path / child).is_symlink()
            )
            for filename in sorted(filenames):
                path = directory_path / filename
                try:
                    if path.is_symlink():
                        continue
                    stat = path.stat()
                    if not S_ISREG(stat.st_mode):
                        continue
                    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    if _utc_naive(modified_at) > cutoff:
                        continue
                    relative = path.relative_to(self._root)
                except (OSError, ValueError):
                    continue
                parsed = self._parse_managed_relative(relative)
                if parsed is None:
                    continue
                artifact_id, is_staging = parsed
                yield ManagedArtifactCandidate(
                    uri=f"local://{relative.as_posix()}",
                    artifact_id=artifact_id,
                    is_staging=is_staging,
                    modified_at=_utc_naive(modified_at),
                    local_relative=relative,
                )

    @staticmethod
    def _parse_managed_relative(relative: Path) -> tuple[UUID, bool] | None:
        parts = relative.parts
        if len(parts) != 4 or not _TENANT_SEGMENT_RE.fullmatch(parts[0]):
            return None
        try:
            UUID(parts[1])
            artifact_id = UUID(parts[2])
        except ValueError:
            return None
        name = parts[3]
        if name in {"", ".", ".."}:
            return None
        staging_suffix = f".staged-{artifact_id}"
        return artifact_id, name.startswith(".") and name.endswith(staging_suffix)

    @staticmethod
    def _safe_name(name: str) -> str:
        safe_name = Path(name).name
        if safe_name in {"", ".", ".."}:
            return "artifact"
        return safe_name

    def _ensure_within_root(self, candidate: Path) -> None:
        if candidate != self._root and self._root not in candidate.parents:
            raise ArtifactStoreError("非法产物路径")


class S3ArtifactStore:
    """S3-compatible Artifact store with Manager-local bounded staging.

    boto3 is synchronous.  Calls are moved to worker threads so FastAPI's
    event loop remains available while MinIO/S3 accepts or serves an object.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region_name: str = "us-east-1",
        prefix: str = "workflow-artifacts",
        staging_root: str | Path | None = None,
        client: object | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 Artifact store 缺少 bucket")
        self._bucket = bucket.strip()
        self._prefix = prefix.strip("/")
        self._staging = LocalArtifactStore(staging_root)
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - deployment guard
                raise RuntimeError("S3 Artifact store 需要 boto3") from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
                region_name=region_name,
            )
        self._client = client

    async def put_bytes(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        content: bytes,
        mime_type: str | None = None,
    ) -> tuple[str, int, str, str]:
        async def chunks() -> AsyncIterator[bytes]:
            yield content

        return await self.put_stream(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            name=name,
            chunks=chunks(),
            mime_type=mime_type,
        )

    async def put_stream(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        chunks: AsyncIterator[bytes],
        mime_type: str | None = None,
        max_bytes: int | None = None,
    ) -> tuple[str, int, str, str]:
        staged = await self.stage_stream(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            name=name,
            chunks=chunks,
            mime_type=mime_type,
            max_bytes=max_bytes,
        )
        try:
            return await self.finalize(staged)
        except BaseException:
            await self.discard(staged)
            raise

    async def stage_stream(
        self,
        *,
        tenant_id: str,
        workflow_run_id: UUID,
        artifact_id: UUID,
        name: str,
        chunks: AsyncIterator[bytes],
        mime_type: str | None = None,
        max_bytes: int | None = None,
    ) -> StagedArtifact:
        return await self._staging.stage_stream(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            name=name,
            chunks=chunks,
            mime_type=mime_type,
            max_bytes=max_bytes,
        )

    def restore_staged(self, **kwargs: object) -> StagedArtifact:
        return self._staging.restore_staged(**kwargs)  # type: ignore[arg-type]

    async def finalize(self, staged: StagedArtifact) -> tuple[str, int, str, str]:
        key = self._key(staged.relative)
        try:
            await asyncio.to_thread(
                self._client.upload_file,
                str(staged.staging),
                self._bucket,
                key,
                ExtraArgs={"ContentType": staged.mime_type},
            )
        except Exception as exc:
            raise ArtifactStoreError("S3 产物上传失败") from exc
        try:
            await self._staging.discard(staged)
        except ArtifactStoreError:
            # The object is already durable.  Keeping a stale local staging
            # file is safe; cleanup can remove it later.
            pass
        return (
            f"s3://{self._bucket}/{key}",
            staged.size_bytes,
            staged.sha256,
            staged.mime_type,
        )

    async def discard(self, staged: StagedArtifact) -> None:
        await self._staging.discard(staged)

    async def read_bytes(self, uri: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream_bytes(uri)])

    async def stream_bytes(self, uri: str) -> AsyncIterator[bytes]:
        key = self._key_from_uri(uri)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            body = response["Body"]
        except Exception as exc:
            raise ArtifactStoreError("产物文件不存在或不可读取") from exc
        try:
            while chunk := await asyncio.to_thread(body.read, 64 * 1024):
                yield chunk
        except Exception as exc:
            raise ArtifactStoreError("产物文件不存在或不可读取") from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    async def file_path(self, uri: str) -> Path:
        del uri
        raise ArtifactStoreError("S3 产物没有本地文件路径")

    async def delete(self, uri: str) -> None:
        key = self._key_from_uri(uri)
        try:
            await asyncio.to_thread(
                self._client.delete_object, Bucket=self._bucket, Key=key
            )
        except Exception as exc:
            raise ArtifactStoreError("S3 产物删除失败") from exc

    async def iter_expired_candidates(
        self, *, cutoff: datetime, max_pages: int | None = None
    ) -> AsyncIterator[ManagedArtifactCandidate]:
        """Yield expired local staging and remote S3 object candidates.

        A non-empty prefix is mandatory for remote scans so a configuration
        mistake cannot enumerate or delete an entire Bucket.
        """
        prefix = self._gc_prefix()
        async for candidate in self._staging.iter_expired_candidates(cutoff=cutoff):
            yield candidate
        token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0
        cutoff = _utc_naive(cutoff)
        while True:
            kwargs: dict[str, str] = {"Bucket": self._bucket, "Prefix": prefix}
            if token is not None:
                kwargs["ContinuationToken"] = token
            try:
                response = await asyncio.to_thread(
                    self._client.list_objects_v2, **kwargs
                )
            except Exception as exc:
                raise ArtifactStoreError("S3 产物枚举失败") from exc
            page_count += 1
            for item in response.get("Contents", []):
                key = item.get("Key")
                modified_at = item.get("LastModified")
                if not isinstance(key, str) or not isinstance(modified_at, datetime):
                    continue
                if _utc_naive(modified_at) > cutoff:
                    continue
                candidate = self._candidate_from_key(key, modified_at)
                if candidate is not None:
                    yield candidate
            if not response.get("IsTruncated", False):
                return
            if max_pages is not None and page_count >= max_pages:
                raise ArtifactStoreError("S3 产物枚举超过单轮页数上限")
            next_token = response.get("NextContinuationToken")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_tokens
            ):
                raise ArtifactStoreError("S3 产物分页游标无效")
            seen_tokens.add(next_token)
            token = next_token

    async def delete_expired_candidate(
        self, candidate: ManagedArtifactCandidate
    ) -> bool:
        if candidate.local_relative is not None:
            return await self._staging.delete_expired_candidate(candidate)
        self._gc_prefix()
        key = self._key_from_uri(candidate.uri)
        if self._candidate_from_key(key, candidate.modified_at) is None:
            raise ArtifactStoreError("非法 S3 产物候选")
        await self.delete(candidate.uri)
        return True

    async def iter_expired_multipart_uploads(
        self, *, cutoff: datetime, max_pages: int | None = None
    ) -> AsyncIterator[MultipartUploadCandidate]:
        """Yield old multipart uploads under the fixed workflow prefix."""
        prefix = self._gc_prefix()
        cutoff = _utc_naive(cutoff)
        key_marker: str | None = None
        upload_id_marker: str | None = None
        seen_markers: set[tuple[str, str | None]] = set()
        page_count = 0
        while True:
            kwargs: dict[str, str] = {"Bucket": self._bucket, "Prefix": prefix}
            if key_marker is not None:
                kwargs["KeyMarker"] = key_marker
            if upload_id_marker is not None:
                kwargs["UploadIdMarker"] = upload_id_marker
            try:
                response = await asyncio.to_thread(
                    self._client.list_multipart_uploads, **kwargs
                )
            except Exception as exc:
                raise ArtifactStoreError("S3 multipart 上传枚举失败") from exc
            page_count += 1
            for item in response.get("Uploads", []):
                key = item.get("Key")
                upload_id = item.get("UploadId")
                initiated_at = item.get("Initiated")
                if (
                    not isinstance(key, str)
                    or not isinstance(upload_id, str)
                    or not isinstance(initiated_at, datetime)
                    or _utc_naive(initiated_at) > cutoff
                ):
                    continue
                candidate = self._candidate_from_key(key, initiated_at)
                if candidate is not None:
                    yield MultipartUploadCandidate(
                        key=key,
                        artifact_id=candidate.artifact_id,
                        upload_id=upload_id,
                        initiated_at=_utc_naive(initiated_at),
                    )
            if not response.get("IsTruncated", False):
                return
            if max_pages is not None and page_count >= max_pages:
                raise ArtifactStoreError("S3 multipart 枚举超过单轮页数上限")
            next_key_marker = response.get("NextKeyMarker")
            next_upload_id_marker = response.get("NextUploadIdMarker")
            if (
                not isinstance(next_key_marker, str)
                or not next_key_marker
                or (
                    next_key_marker,
                    (
                        next_upload_id_marker
                        if isinstance(next_upload_id_marker, str)
                        else None
                    ),
                )
                in seen_markers
            ):
                raise ArtifactStoreError("S3 multipart 分页游标无效")
            seen_markers.add(
                (
                    next_key_marker,
                    (
                        next_upload_id_marker
                        if isinstance(next_upload_id_marker, str)
                        else None
                    ),
                )
            )
            key_marker = next_key_marker
            upload_id_marker = (
                next_upload_id_marker
                if isinstance(next_upload_id_marker, str)
                else None
            )

    async def abort_expired_multipart_upload(
        self, candidate: MultipartUploadCandidate
    ) -> bool:
        self._gc_prefix()
        if self._candidate_from_key(candidate.key, candidate.initiated_at) is None:
            raise ArtifactStoreError("非法 S3 multipart 候选")
        try:
            await asyncio.to_thread(
                self._client.abort_multipart_upload,
                Bucket=self._bucket,
                Key=candidate.key,
                UploadId=candidate.upload_id,
            )
        except Exception as exc:
            if self._is_missing_upload(exc):
                return False
            raise ArtifactStoreError("S3 multipart 上传中止失败") from exc
        return True

    def _key(self, relative: Path) -> str:
        return "/".join(part for part in (self._prefix, relative.as_posix()) if part)

    def _gc_prefix(self) -> str:
        if not self._prefix:
            raise ArtifactStoreError("S3 产物 GC 需要非空前缀")
        return f"{self._prefix}/"

    def _candidate_from_key(
        self, key: str, modified_at: datetime
    ) -> ManagedArtifactCandidate | None:
        prefix = self._gc_prefix()
        if not key.startswith(prefix):
            return None
        relative = PurePosixPath(key.removeprefix(prefix))
        parsed = LocalArtifactStore._parse_managed_relative(Path(*relative.parts))
        if parsed is None:
            return None
        artifact_id, is_staging = parsed
        return ManagedArtifactCandidate(
            uri=f"s3://{self._bucket}/{key}",
            artifact_id=artifact_id,
            is_staging=is_staging,
            modified_at=_utc_naive(modified_at),
        )

    @staticmethod
    def _is_missing_upload(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        error = response.get("Error")
        if not isinstance(error, dict):
            return False
        return str(error.get("Code", "")) in {
            "404",
            "NoSuchKey",
            "NoSuchUpload",
            "NotFound",
        }

    def _key_from_uri(self, uri: str) -> str:
        prefix = f"s3://{self._bucket}/"
        if not uri.startswith(prefix):
            raise ArtifactStoreError("不支持的产物 URI")
        key = uri.removeprefix(prefix)
        expected_prefix = f"{self._prefix}/" if self._prefix else ""
        if not key or (expected_prefix and not key.startswith(expected_prefix)):
            raise ArtifactStoreError("非法产物路径")
        return key


def _artifact_store_from_settings() -> LocalArtifactStore | S3ArtifactStore:
    backend = settings.workflow_artifact_backend.strip().lower()
    if backend == "s3":
        return S3ArtifactStore(
            bucket=settings.workflow_artifact_s3_bucket,
            endpoint_url=settings.workflow_artifact_s3_endpoint_url,
            access_key_id=settings.workflow_artifact_s3_access_key_id,
            secret_access_key=settings.workflow_artifact_s3_secret_access_key,
            region_name=settings.workflow_artifact_s3_region,
            prefix=settings.workflow_artifact_s3_prefix,
        )
    if backend == "local":
        return LocalArtifactStore()
    raise RuntimeError(f"不支持的工作流 Artifact 后端：{backend}")


artifact_store = _artifact_store_from_settings()

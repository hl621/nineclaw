"""Skill registry routes.

Public, manager-level skills (not per-tenant). Storage path comes from
``settings.skills_storage_path``. The filesystem is the only source of
truth — every endpoint scans/writes the directory and never persists
metadata in the database.

Routes:
- GET    /skills                          – list every skill on disk
- GET    /skills/{slug}                   – metadata + raw SKILL.md body
- POST   /skills/upload                   – single-skill multipart zip upload
- POST   /skills/preview                  – multi-skill detection (returns session)
- POST   /skills/import                   – SSE: import previewed skills one-by-one
- POST   /skills/deploy                   – SSE: deploy skills to nineclaw instances
- DELETE /skills/preview/{session_id}     – discard an unused preview session
- GET    /skills/{slug}/download          – download the skill folder as zip
- DELETE /skills/{slug}                   – remove the skill from disk
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.instance import ServiceInstance
from app.schemas.skill import SkillCreateRequest, SkillDetailResponse, SkillResponse
from app.services.docker_client import create_configured_docker_client
from app.services.instance_agent_snapshot import persist_manager_resource_snapshot
from app.services.skill_service import SkillError, SkillService
from app.services.skill_upload_session import (
    UploadSessionStore,
    get_upload_session_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/skills",
    tags=["skills"],
)


class ApiResponse(BaseModel):
    """Standard envelope used across the manager API."""

    code: int = Field(default=0)
    message: str = Field(default="success")
    data: Any = Field(default=None)


def get_skill_service() -> SkillService:
    return SkillService(
        storage_root=settings.skills_storage_path,
        max_upload_size=settings.skills_max_upload_size,
    )


# ─── List ────────────────────────────────────────────────────────────────────


@router.get("", response_model=ApiResponse, summary="List skills on disk")
async def list_skills(
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    items = [
        SkillResponse.model_validate(record).model_dump(mode="json")
        for record in service.list_skills()
    ]
    return ApiResponse(
        data={
            "items": items,
            "total": len(items),
            "storage_path": str(service.storage_root),
        }
    )


# Note: ordering matters — the `/preview` and `/upload` collection
# endpoints must be declared before `/{slug}` so FastAPI doesn't route
# the literal paths into the slug parameter.


# ─── Create empty skill ──────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a skill from name and description",
)
async def create_skill(
    body: SkillCreateRequest,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    record = service.create_skill(body.name, body.description)
    return ApiResponse(
        data=SkillResponse.model_validate(record).model_dump(mode="json")
    )


# ─── Single-skill upload (programmatic / CLI) ────────────────────────────────


@router.post(
    "/upload",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a zipped single skill (no preview)",
)
async def upload_skill(
    file: UploadFile = File(
        ..., description="Zip archive containing the skill folder."
    ),
    overwrite: bool = Form(
        default=False,
        description="If true, replace an existing skill with the same slug.",
    ),
    slug: str | None = Form(
        default=None,
        description=(
            "Optional override slug. When omitted the slug is taken from "
            "the zip's top-level directory or from frontmatter `name`."
        ),
    ),
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    contents = await file.read(service.max_upload_size + 1)
    if len(contents) > service.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"上传文件超过上限 {service.max_upload_size / (1024 * 1024):.0f}MiB"
            ),
        )

    suggested = slug or _slug_from_filename(file.filename)
    record = service.save_zip_upload(
        contents,
        overwrite=overwrite,
        suggested_slug=suggested,
    )
    return ApiResponse(
        data=SkillResponse.model_validate(record).model_dump(mode="json")
    )


def _slug_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base.lower().endswith(".zip"):
        base = base[:-4]
    return base or None


# ─── Multi-skill preview + SSE import ────────────────────────────────────────

TENANT_HEADER = "X-Tenant-ID"


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    return x_tenant_id or settings.default_tenant_id


@router.post(
    "/preview",
    response_model=ApiResponse,
    summary="Recursively detect skills inside a zip and create an import session",
)
async def preview_skills_zip(
    file: UploadFile = File(...),
    instance_id: str | None = Form(default=None),
    service: SkillService = Depends(get_skill_service),
    sessions: UploadSessionStore = Depends(get_upload_session_store),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    contents = await file.read(service.max_upload_size + 1)
    if len(contents) > service.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"上传文件超过上限 {service.max_upload_size / (1024 * 1024):.0f}MiB"
            ),
        )

    detected = service.detect_skills_in_zip(contents)

    # 实例专属上传：conflicts 改为对照实例内已有技能（而非共享库）。
    if instance_id:
        try:
            docker = await create_configured_docker_client(tenant_id=tenant_id)
            try:
                container = await docker.containers.get(
                    f"{settings.nineclaw_container_name_prefix}-{instance_id}"
                )
                existing = await _existing_skill_dirs(container)
                for record in detected:
                    slug = record.get("slug")
                    record["conflicts"] = bool(slug and slug in existing)
            finally:
                await docker.close()
        except Exception as exc:  # noqa: BLE001 — 查询失败退化为不标冲突
            logger.warning(
                "preview: failed to read instance skills for %s: %s",
                instance_id,
                exc,
            )

    session = sessions.create(
        zip_bytes=contents,
        filename=file.filename or "upload.zip",
        detected=detected,
    )
    return ApiResponse(
        data={
            "session_id": session.session_id,
            "filename": session.filename,
            "skills": [_public_detection(d) for d in detected],
            "total": len(detected),
            "ttl_seconds": int(sessions.ttl),
        }
    )


def _public_detection(record: dict[str, Any]) -> dict[str, Any]:
    """Trim internal fields out of a detection record before serialising."""
    keys = (
        "slug",
        "name",
        "description",
        "author",
        "license",
        "tags",
        "conflicts",
        "error",
        "skill_md_path",
    )
    return {k: record.get(k) for k in keys}


class ImportRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128)
    overwrite: bool = Field(
        default=False,
        description="Apply to every skill in the batch.",
    )
    slugs: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of slugs to import. When null all detected "
            "skills with no validation error are imported."
        ),
    )


@router.post(
    "/import",
    summary="Stream-import previously previewed skills one-by-one (SSE)",
)
async def import_skills(
    body: ImportRequest = Body(...),
    service: SkillService = Depends(get_skill_service),
    sessions: UploadSessionStore = Depends(get_upload_session_store),
) -> EventSourceResponse:
    session = sessions.get(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="预览会话不存在或已过期，请重新上传。",
        )

    requested: list[dict[str, Any]]
    if body.slugs:
        wanted = set(body.slugs)
        requested = [d for d in session.detected if d["slug"] in wanted]
        missing = wanted - {d["slug"] for d in session.detected}
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"会话中不存在以下 slug：{sorted(missing)}",
            )
    else:
        requested = list(session.detected)

    overwrite = body.overwrite

    async def stream() -> AsyncGenerator[dict[str, Any], None]:
        imported = 0
        failed = 0
        skipped = 0
        try:
            for record in requested:
                slug = record.get("slug") or ""
                name = record.get("name") or slug or record.get("skill_md_path") or ""

                # Skill flagged with an error during preview — surface
                # it as a "failed" event without touching disk.
                if record.get("error"):
                    failed += 1
                    yield _sse(
                        "status",
                        {
                            "slug": slug,
                            "name": name,
                            "status": "failed",
                            "error": record["error"],
                        },
                    )
                    continue

                yield _sse(
                    "status",
                    {"slug": slug, "name": name, "status": "importing"},
                )
                # Yield a tick so the event actually flushes before the
                # blocking install runs to completion.
                await asyncio.sleep(0)

                try:
                    installed = await asyncio.to_thread(
                        service.install_skill_from_zip_bytes,
                        session.zip_bytes,
                        slug=slug,
                        zip_root_prefix=record["zip_root_prefix"],
                        overwrite=overwrite,
                    )
                except SkillError as exc:
                    if exc.status_code == status.HTTP_409_CONFLICT and not overwrite:
                        skipped += 1
                        yield _sse(
                            "status",
                            {
                                "slug": slug,
                                "name": name,
                                "status": "skipped",
                                "error": str(exc.detail),
                            },
                        )
                    else:
                        failed += 1
                        yield _sse(
                            "status",
                            {
                                "slug": slug,
                                "name": name,
                                "status": "failed",
                                "error": str(exc.detail),
                            },
                        )
                except Exception as exc:  # noqa: BLE001 — surfaced to client
                    logger.exception("skill import crashed for slug %s", slug)
                    failed += 1
                    yield _sse(
                        "status",
                        {
                            "slug": slug,
                            "name": name,
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                else:
                    imported += 1
                    yield _sse(
                        "status",
                        {
                            "slug": slug,
                            "name": name,
                            "status": "imported",
                            "skill": SkillResponse.model_validate(installed).model_dump(
                                mode="json"
                            ),
                        },
                    )
        finally:
            sessions.delete(session.session_id)

        yield _sse(
            "done",
            {"imported": imported, "failed": failed, "skipped": skipped},
        )

    return EventSourceResponse(stream())


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@router.delete(
    "/preview/{session_id}",
    response_model=ApiResponse,
    summary="Discard an unused preview session",
)
async def cancel_preview(
    session_id: str,
    sessions: UploadSessionStore = Depends(get_upload_session_store),
) -> ApiResponse:
    deleted = sessions.delete(session_id)
    return ApiResponse(data={"deleted": deleted})


# ─── Deploy skills to nineclaw instances ─────────────────────────────────────

_NATIVE_SKILLS_ROOT = "/opt/data/skills"


class DeploySkillsRequest(BaseModel):
    skill_slugs: list[str] = Field(..., min_length=1)
    instance_ids: list[str] = Field(..., min_length=1)
    # Optional target category. When set, skills are placed under
    # /opt/data/skills/{category}/{slug} so they show up under that category.
    # When unset, skills go directly under /opt/data/skills/{slug} (uncategorised).
    # Both are in Hermes' native scan path and show up in the instance skill list.
    category: str | None = None
    # When set, skills are taken straight from the previewed upload session and
    # deployed to the instances WITHOUT being imported into the shared skill
    # library (instance-scoped upload).
    upload_session_id: str | None = Field(default=None, min_length=8, max_length=128)
    # 实例内已存在同名技能时是否覆盖（覆盖=删掉旧副本再部署到目标分类，
    # 等价于把技能移动到目标分类，保证一个技能在实例里只有一份）。
    overwrite: bool = False


async def _existing_skill_dirs(container) -> dict[str, str]:
    """Map slug -> absolute dir path for skills already present in the instance.

    Scans ``/opt/data/skills`` for SKILL.md files at depth <= 3, covering both
    uncategorised skills (``/opt/data/skills/{slug}/``) and categorised ones
    (``/opt/data/skills/{category}/{slug}/``).
    """
    exec_obj = await container.exec(
        ["sh", "-c", "find /opt/data/skills -maxdepth 3 -name SKILL.md 2>/dev/null"],
        stdout=True,
        stderr=True,
    )
    chunks: list[str] = []
    async with exec_obj.start(detach=False) as stream:
        while True:
            msg = await stream.read_out()
            if msg is None:
                break
            chunks.append(msg.data.decode(errors="replace"))
    result: dict[str, str] = {}
    for line in "".join(chunks).splitlines():
        line = line.strip()
        suffix = "/SKILL.md"
        if not line.endswith(suffix):
            continue
        skill_dir = line[: -len(suffix)]
        slug = skill_dir.rsplit("/", 1)[-1]
        if slug:
            result[slug] = skill_dir
    return result


@router.post(
    "/deploy",
    summary="Stream deployment of selected skills to selected NineClaw instances (SSE)",
)
async def deploy_skills(
    body: DeploySkillsRequest = Body(...),
    tenant_id: str = Depends(get_tenant_id),
    service: SkillService = Depends(get_skill_service),
    sessions: UploadSessionStore = Depends(get_upload_session_store),
) -> EventSourceResponse:
    import shutil
    import tempfile

    upload_session = None
    if body.upload_session_id:
        upload_session = sessions.get(body.upload_session_id)
        if upload_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="预览会话不存在或已过期，请重新上传。",
            )

    skill_records: list[dict[str, Any]] = []
    staged_root: Path | None = None
    if upload_session is not None:
        # Instance-scoped deploy: stage skills from the upload session zip
        # into a temp dir; they never touch the shared skill library.
        detected_by_slug = {
            d.get("slug"): d
            for d in upload_session.detected
            if d.get("slug")
        }
        missing = [s for s in body.skill_slugs if s not in detected_by_slug]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"上传会话中不存在以下 slug：{sorted(missing)}",
            )
        staged_root = Path(tempfile.mkdtemp(prefix="skill-deploy-"))
        try:
            for slug in body.skill_slugs:
                record = detected_by_slug[slug]
                if record.get("error"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"技能 '{slug}' 校验失败：{record['error']}",
                    )
                meta = await asyncio.to_thread(
                    service.stage_skill_from_zip_bytes,
                    upload_session.zip_bytes,
                    slug=slug,
                    zip_root_prefix=record.get("zip_root_prefix") or "",
                    dest_parent=staged_root,
                )
                skill_records.append(
                    {
                        "id": slug,
                        "name": meta.get("name") or slug,
                        "_src": str((staged_root / slug)),
                    }
                )
        except SkillError as exc:
            shutil.rmtree(staged_root, ignore_errors=True)
            raise HTTPException(
                status_code=exc.status_code, detail=str(exc.detail)
            ) from exc
    else:
        for slug in body.skill_slugs:
            try:
                skill_records.append(service.get_skill(slug))
            except SkillError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"技能 '{slug}' 不存在",
                )

    async with async_session_maker() as session:
        inst_stmt = select(ServiceInstance).where(
            ServiceInstance.tenant_id == tenant_id,
            ServiceInstance.id.in_(body.instance_ids),
        )
        instances = list((await session.execute(inst_stmt)).scalars().all())

    if len(instances) != len(set(body.instance_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="部分实例不存在或不属于当前租户",
        )

    inst_by_id = {i.id: i for i in instances}
    ordered_instances = [
        inst_by_id[iid] for iid in body.instance_ids if iid in inst_by_id
    ]

    storage_root = Path(service.storage_root)
    container_name_prefix = settings.nineclaw_container_name_prefix

    async def event_stream() -> AsyncGenerator[dict[str, Any], None]:
        for inst in ordered_instances:
            yield _sse(
                "status",
                {
                    "instance_id": inst.id,
                    "name": inst.name,
                    "status": "pending",
                    "skill_slug": None,
                    "error": None,
                },
            )

        for inst in ordered_instances:
            yield _sse(
                "status",
                {
                    "instance_id": inst.id,
                    "name": inst.name,
                    "status": "deploying",
                    "skill_slug": None,
                    "error": None,
                },
            )

            actual = (inst.actual_state or "").lower()
            if actual != "running":
                yield _sse(
                    "status",
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "failed",
                        "skill_slug": None,
                        "error": f"实例当前状态为 {actual or 'unknown'}，必须运行中才能部署",
                    },
                )
                continue

            # 技能统一落到 Hermes 原生扫描根 /opt/data/skills：
            # 有分类 → /opt/data/skills/{category}/{slug}/，
            # 无分类 → /opt/data/skills/{slug}/（与实例自身 /skills/save
            # 对未分类技能的存放约定一致，实测可直接出现在技能列表）。
            # 旧的 /opt/nineclaw/external_skill + skills.external_dirs 方案
            # 在当前实例镜像里不会被扫描（部署"成功"但列表不显示），已弃用。
            dest_dir = (
                f"{_NATIVE_SKILLS_ROOT}/{body.category}"
                if body.category
                else _NATIVE_SKILLS_ROOT
            )

            container_name = f"{container_name_prefix}-{inst.id}"
            failed_skill: str | None = None
            try:
                import io
                import shlex
                import tarfile

                docker = await create_configured_docker_client(tenant_id=tenant_id)
                try:
                    container = await docker.containers.get(container_name)
                    # Ensure destination directory exists inside container.
                    exec_obj = await container.exec(
                        ["mkdir", "-p", dest_dir],
                        stdout=True,
                        stderr=True,
                    )
                    async with exec_obj.start(detach=False) as stream:
                        while await stream.read_out() is not None:
                            pass

                    # 实例内已存在的技能（slug -> 目录），用于查重/覆盖。
                    existing_dirs = await _existing_skill_dirs(container)

                    deployed_records: list[dict[str, Any]] = []
                    for record in skill_records:
                        slug = record["id"]
                        failed_skill = slug
                        existing_path = existing_dirs.get(slug)
                        if existing_path and not body.overwrite:
                            # 实例里已有同名技能：不覆盖则跳过（提示重复）。
                            yield _sse(
                                "status",
                                {
                                    "instance_id": inst.id,
                                    "name": inst.name,
                                    "status": "skipped",
                                    "skill_slug": slug,
                                    "error": f"技能 {slug} 已存在于实例，未覆盖",
                                },
                            )
                            failed_skill = None
                            continue
                        if existing_path and body.overwrite:
                            # 覆盖=先删掉旧副本（无论它在哪个分类），再部署到
                            # 目标分类，保证一个技能在实例里只有一份。
                            rm_obj = await container.exec(
                                ["rm", "-rf", existing_path],
                                stdout=True,
                                stderr=True,
                            )
                            async with rm_obj.start(detach=False) as stream:
                                while await stream.read_out() is not None:
                                    pass
                        src = (
                            Path(record["_src"])
                            if record.get("_src")
                            else storage_root / slug
                        )
                        buf = io.BytesIO()
                        with tarfile.open(fileobj=buf, mode="w") as tar:
                            tar.add(str(src), arcname=slug)
                        await container.put_archive(
                            dest_dir, buf.getvalue()
                        )
                        deployed_records.append(record)
                        yield _sse(
                            "status",
                            {
                                "instance_id": inst.id,
                                "name": inst.name,
                                "status": "imported",
                                "skill_slug": slug,
                                "error": None,
                            },
                        )
                        failed_skill = None

                    # 属主修正：put_archive 写入的文件归 root，而实例 webui
                    # 以 hermes 用户运行，无权限删除/移动这些技能（报 500
                    # PermissionError）。把新写入的目录属主对齐技能根目录。
                    if deployed_records:
                        chown_targets = " ".join(
                            shlex.quote(f"{dest_dir}/{record['id']}")
                            for record in deployed_records
                        )
                        if dest_dir != _NATIVE_SKILLS_ROOT:
                            chown_targets = f"{shlex.quote(dest_dir)} {chown_targets}"
                        fix_owner_cmd = (
                            f"OW=$(stat -c %u:%g {_NATIVE_SKILLS_ROOT}) && "
                            f'chown -R "$OW" {chown_targets}'
                        )
                        failed_skill = "(chown)"
                        exec_obj = await container.exec(
                            ["sh", "-c", fix_owner_cmd],
                            stdout=True,
                            stderr=True,
                        )
                        async with exec_obj.start(detach=False) as stream:
                            while await stream.read_out() is not None:
                                pass
                        failed_skill = None
                finally:
                    await docker.close()
                if deployed_records:
                    async with async_session_maker() as snapshot_session:
                        await persist_manager_resource_snapshot(
                            snapshot_session,
                            tenant_id=tenant_id,
                            instance_id=inst.id,
                            skills=[
                                {
                                    "slug": str(record["id"]),
                                    "name": str(record.get("name") or record["id"]),
                                }
                                for record in deployed_records
                            ],
                        )
                        await snapshot_session.commit()
            except Exception as exc:
                yield _sse(
                    "status",
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "failed",
                        "skill_slug": failed_skill,
                        "error": str(exc),
                    },
                )
                continue

            yield _sse(
                "status",
                {
                    "instance_id": inst.id,
                    "name": inst.name,
                    "status": "deployed",
                    "skill_slug": None,
                    "error": None,
                },
            )

        # 实例专属上传：部署结束后清理上传会话与临时目录（技能不进共享库）
        if upload_session is not None:
            try:
                sessions.delete(upload_session.session_id)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.warning(
                    "failed to delete upload session %s",
                    upload_session.session_id,
                )
        if staged_root is not None:
            shutil.rmtree(staged_root, ignore_errors=True)

        yield _sse("done", {"finished": True})

    return EventSourceResponse(event_stream())


# ─── Per-skill detail / download / delete (slug-routed) ─────────────────────


@router.get(
    "/{slug}",
    response_model=ApiResponse,
    summary="Get skill metadata and SKILL.md body",
)
async def get_skill(
    slug: str,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    record = service.get_skill(slug)
    return ApiResponse(
        data=SkillDetailResponse.model_validate(record).model_dump(mode="json")
    )


@router.get(
    "/{slug}/download",
    summary="Download a skill folder as a zip archive",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive of the skill folder.",
        }
    },
)
async def download_skill(
    slug: str,
    service: SkillService = Depends(get_skill_service),
) -> Response:
    filename, payload = service.build_zip(slug)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


@router.delete(
    "/{slug}",
    response_model=ApiResponse,
    summary="Delete a skill from disk",
)
async def delete_skill(
    slug: str,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    service.delete_skill(slug)
    return ApiResponse(data={"deleted": slug})


# ─── Refresh (no-op shortcut for the UI) ─────────────────────────────────────


@router.post(
    "/refresh",
    response_model=ApiResponse,
    summary="Re-scan the storage directory (alias for GET /skills)",
)
async def refresh_skills(
    _force: bool = Query(default=False, alias="force"),
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    items = [
        SkillResponse.model_validate(record).model_dump(mode="json")
        for record in service.list_skills()
    ]
    return ApiResponse(
        data={
            "items": items,
            "total": len(items),
            "storage_path": str(service.storage_root),
        }
    )

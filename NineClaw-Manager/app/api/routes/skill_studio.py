"""Skill studio routes: file browser + LLM chat for a single skill."""

from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.skills import ApiResponse, get_skill_service
from app.core.config import settings
from app.db.session import get_session
from app.schemas.skill_studio import (
    SkillStudioChatRequest,
    SkillStudioCreateSessionRequest,
    SkillStudioCreateSessionResponse,
    SkillStudioDeleteFileRequest,
    SkillStudioFileContentResponse,
    SkillStudioFileListResponse,
    SkillStudioCancelRequest,
    SkillStudioMoveFileRequest,
    SkillStudioQaRequest,
    SkillStudioSaveFileRequest,
)
from app.services.skill_service import SkillService
from app.services.knowledge_llm_service import (
    QaLlmError,
    resolve_qa_llm_with_db_fallback,
)
from app.services.skill_studio_chat import (
    cancel_run,
    create_session,
    process_studio_chat_stream,
    process_studio_qa_stream,
)
from app.services.skill_studio_files import (
    _resolve_relative,
    delete_skill_path,
    list_skill_files,
    move_skill_path,
    read_skill_file,
    save_skill_file,
    upload_skill_file,
)
from app.services.skill_studio_watch import watch_skill_files

router = APIRouter(prefix="/skills", tags=["skill-studio"])

TENANT_HEADER = "X-Tenant-ID"


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    return x_tenant_id or settings.default_tenant_id


async def _resolve_studio_llm(
    session: AsyncSession,
    tenant_id: str,
    provider_id: str | None,
    model: str | None,
):
    try:
        return await resolve_qa_llm_with_db_fallback(
            session,
            tenant_id,
            provider_id,
            model,
        )
    except QaLlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _skill_root_path(service: SkillService, slug: str):
    from app.services.skill_studio_files import _skill_root

    return _skill_root(service, slug)


@router.get("/{slug}/studio/files", response_model=ApiResponse)
async def list_studio_files(
    slug: str,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    files = list_skill_files(service, slug)
    payload = SkillStudioFileListResponse(slug=slug, files=files).model_dump(
        mode="json"
    )
    return ApiResponse(data=payload)


@router.get("/{slug}/studio/files/content", response_model=ApiResponse)
async def get_studio_file_content(
    slug: str,
    path: str = Query(..., description="Relative file path within the skill folder."),
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    record = read_skill_file(service, slug, path)
    data = SkillStudioFileContentResponse.model_validate(record).model_dump(mode="json")
    return ApiResponse(data=data)


@router.put("/{slug}/studio/files/content", response_model=ApiResponse)
async def save_studio_file_content(
    slug: str,
    body: SkillStudioSaveFileRequest,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    record = save_skill_file(service, slug, body.path, body.content)
    data = SkillStudioFileContentResponse.model_validate(record).model_dump(mode="json")
    return ApiResponse(data=data)


@router.post("/{slug}/studio/files/upload", response_model=ApiResponse)
async def upload_studio_file(
    slug: str,
    file: UploadFile = File(...),
    path: str = Form(..., description="Relative target path within the skill folder."),
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    """Upload one file (code or asset) into the skill folder.

    ``path`` is the target relative path including the file name, e.g.
    ``assets/logo.png``. Parent folders are created automatically; an existing
    file at the same path is overwritten.
    """
    payload = await file.read()
    record = upload_skill_file(service, slug, path, payload)
    data = SkillStudioFileContentResponse.model_validate(record).model_dump(mode="json")
    return ApiResponse(data=data)


@router.get("/{slug}/studio/files/raw")
async def get_studio_file_raw(
    slug: str,
    path: str = Query(..., description="Relative file path within the skill folder."),
    download: bool = Query(default=False, description="Force download instead of inline."),
    service: SkillService = Depends(get_skill_service),
):
    """Serve raw file bytes for in-browser preview (img/pdf/docx/xlsx) or download."""
    root = _skill_root_path(service, slug)
    target = _resolve_relative(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"未找到文件：{path}")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name if download else None,
    )


@router.post("/{slug}/studio/files/delete", response_model=ApiResponse)
async def delete_studio_file(
    slug: str,
    body: SkillStudioDeleteFileRequest,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    """Delete a file or folder (recursively) within the skill folder.

    The root ``SKILL.md`` is the skill identity file and cannot be deleted.
    """
    data = delete_skill_path(service, slug, body.path)
    return ApiResponse(data=data)


@router.post("/{slug}/studio/files/move", response_model=ApiResponse)
async def move_studio_file(
    slug: str,
    body: SkillStudioMoveFileRequest,
    service: SkillService = Depends(get_skill_service),
) -> ApiResponse:
    """Move/rename a file or folder within the skill folder.

    ``dest`` is the target relative path including the file name; parent
    folders are created automatically. Fails when the destination exists.
    """
    data = move_skill_path(service, slug, body.src, body.dest)
    return ApiResponse(data=data)


@router.get("/{slug}/studio/watch")
async def watch_studio_files(
    slug: str,
    service: SkillService = Depends(get_skill_service),
    tenant_id: str = Depends(get_tenant_id),
):
    root = _skill_root_path(service, slug)
    return StreamingResponse(
        watch_skill_files(tenant_id, slug, root),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{slug}/studio/chat/session", response_model=ApiResponse)
async def create_studio_session(
    slug: str,
    body: SkillStudioCreateSessionRequest | None = None,
    service: SkillService = Depends(get_skill_service),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    _skill_root_path(service, slug)
    category = body.category if body else None
    data = create_session(slug, category, tenant_id=tenant_id)
    return ApiResponse(
        data=SkillStudioCreateSessionResponse.model_validate(data).model_dump(
            mode="json"
        )
    )


def _validate_chat_body(body: SkillStudioChatRequest | SkillStudioQaRequest) -> None:
    if body.resume_run_id:
        return
    if not body.message or not body.message.strip():
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="message 不能为空")


@router.post("/{slug}/studio/chat/cancel", response_model=ApiResponse)
async def cancel_studio_chat(
    slug: str,
    body: SkillStudioCancelRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    ok = cancel_run(
        body.run_id, tenant_id=tenant_id, slug=slug, session_id=body.session_id
    )
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="流式任务不存在或已结束")
    return ApiResponse(data={"run_id": body.run_id, "status": "canceled"})


@router.post("/{slug}/studio/chat")
async def studio_chat(
    slug: str,
    body: SkillStudioChatRequest,
    service: SkillService = Depends(get_skill_service),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    _validate_chat_body(body)
    root = _skill_root_path(service, slug)
    llm = None
    if not body.resume_run_id:
        llm = await _resolve_studio_llm(
            session,
            tenant_id,
            body.provider_id,
            body.model,
        )

    async def event_gen():
        async for chunk in process_studio_chat_stream(
            tenant_id,
            slug,
            body.session_id,
            body.message or "",
            root,
            body.category,
            body.resume_run_id,
            body.from_index,
            llm=llm,
            temperature=body.temperature,
            enable_thinking=body.enable_thinking,
        ):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{slug}/studio/chat/qa")
async def studio_chat_qa(
    slug: str,
    body: SkillStudioQaRequest,
    service: SkillService = Depends(get_skill_service),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    _validate_chat_body(body)
    root = _skill_root_path(service, slug)
    llm = None
    if not body.resume_run_id:
        llm = await _resolve_studio_llm(
            session,
            tenant_id,
            body.provider_id,
            body.model,
        )

    async def event_gen():
        async for chunk in process_studio_qa_stream(
            tenant_id,
            slug,
            body.session_id,
            body.message or "",
            root,
            service,
            body.resume_run_id,
            body.from_index,
            llm=llm,
            temperature=body.temperature,
            enable_thinking=body.enable_thinking,
        ):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

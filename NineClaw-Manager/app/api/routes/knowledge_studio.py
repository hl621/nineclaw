"""Knowledge studio routes — RAG Q&A chat aligned with skill studio."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.knowledge import (
    ApiResponse,
    get_knowledge_service_dep,
    get_tenant_id,
)
from app.db.session import get_session
from app.schemas.knowledge_studio import (
    KnowledgeStudioCancelRequest,
    KnowledgeStudioCreateSessionRequest,
    KnowledgeStudioCreateSessionResponse,
    KnowledgeStudioQaRequest,
)
from app.services.knowledge_factory import KnowledgeBackend, KnowledgeError
from app.services.knowledge_llm_service import (
    QaLlmError,
    resolve_qa_llm_with_db_fallback,
)
from app.services.knowledge_assistant_runtime import (
    LEGACY_SSE_HEADERS,
    cancel_studio_run,
    create_knowledge_studio_assistant_session,
    process_knowledge_studio_assistant_stream,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge-studio"])


def _ensure_kb(service: KnowledgeBackend, kb_id: str) -> None:
    try:
        service.ensure_exists(kb_id)
    except KnowledgeError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc.detail)
        ) from exc


def _validate_qa_body(body: KnowledgeStudioQaRequest) -> None:
    if body.resume_run_id:
        return
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=422, detail="message 不能为空")


@router.post("/{kb_id}/studio/chat/session", response_model=ApiResponse)
async def create_kb_studio_session(
    kb_id: str,
    body: KnowledgeStudioCreateSessionRequest | None = None,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    _ensure_kb(service, kb_id)
    category = body.category if body else None
    data = create_knowledge_studio_assistant_session(
        kb_id, category, tenant_id=tenant_id
    )
    payload = KnowledgeStudioCreateSessionResponse.model_validate(data).model_dump(
        mode="json"
    )
    return ApiResponse(data=payload)


@router.post("/{kb_id}/studio/chat/cancel", response_model=ApiResponse)
async def cancel_kb_studio_chat(
    kb_id: str,
    body: KnowledgeStudioCancelRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    ok = cancel_studio_run(
        body.run_id,
        tenant_id=tenant_id,
        kb_id=kb_id,
        session_id=body.session_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="流式任务不存在或已结束")
    return ApiResponse(data={"run_id": body.run_id, "status": "canceled"})


@router.post("/{kb_id}/studio/chat/qa")
async def kb_studio_chat_qa(
    kb_id: str,
    body: KnowledgeStudioQaRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """SSE 知识问答，事件格式与 ``POST /skills/{slug}/studio/chat/qa`` 一致。"""
    _validate_qa_body(body)
    _ensure_kb(service, kb_id)

    llm = None
    if not body.resume_run_id:
        try:
            llm = await resolve_qa_llm_with_db_fallback(
                session,
                tenant_id,
                body.provider_id,
                body.model,
            )
        except QaLlmError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_gen():
        async for chunk in process_knowledge_studio_assistant_stream(
            tenant_id,
            kb_id,
            body.session_id,
            body.message or "",
            service,
            resume_run_id=body.resume_run_id,
            from_index=body.from_index,
            llm=llm,
            top_k=body.top_k,
            rerank_id=body.rerank_id,
            tenant_rerank_id=body.tenant_rerank_id,
            temperature=body.temperature,
            enable_thinking=body.enable_thinking,
            cross_languages=body.cross_languages,
        ):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers=LEGACY_SSE_HEADERS,
    )

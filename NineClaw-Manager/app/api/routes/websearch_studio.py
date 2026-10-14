"""Chat endpoints for AI-assisted WebSearch extractor development."""

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.schemas.websearch_studio import (
    WebSearchStudioCancelRequest,
    WebSearchStudioChatRequest,
    WebSearchStudioSessionResponse,
)
from app.services.knowledge_llm_service import (
    QaLlmError,
    resolve_qa_llm_with_db_fallback,
)
from app.services.websearch_studio_chat import cancel_run, create_session, stream_chat

router = APIRouter(prefix="/websearch-studio", tags=["websearch-studio"])


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID")
) -> str:
    return x_tenant_id or settings.default_tenant_id


@router.post("/{source_id}/session", response_model=WebSearchStudioSessionResponse)
async def create_websearch_session(
    source_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    return WebSearchStudioSessionResponse(
        session_id=create_session(source_id, tenant_id)
    )


@router.post("/{source_id}/chat")
async def websearch_chat(
    source_id: str,
    body: WebSearchStudioChatRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_session),
):
    try:
        llm = await resolve_qa_llm_with_db_fallback(
            db, tenant_id, body.provider_id, body.model
        )
    except QaLlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def generate():
        try:
            async for chunk in stream_chat(
                source_id,
                tenant_id,
                body.session_id,
                body.message,
                llm,
                body.temperature,
                body.enable_thinking,
            ):
                yield chunk
        except RuntimeError as exc:
            payload = json.dumps(
                {"type": "error", "message": str(exc)}, ensure_ascii=False
            )
            yield f"event: reasoning\ndata: {payload}\n\n"
            yield "event: reasoning\ndata: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{source_id}/cancel")
async def cancel_websearch_chat(
    source_id: str,
    body: WebSearchStudioCancelRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    if not cancel_run(source_id, tenant_id, body.session_id, body.run_id):
        raise HTTPException(status_code=404, detail="任务不存在或已经结束")
    return {"run_id": body.run_id, "status": "canceling"}

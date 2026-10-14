"""RAGFlow-compatible retrieval route alias.

Exposes ``POST /v1/retrieval`` (same as RAGFlow ``POST /api/v1/retrieval``).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.schemas.retrieval import RetrievalRequest
from app.services.knowledge_factory import KnowledgeBackend, _get_knowledge_service
from app.services.knowledge_retrieval_service import build_retrieval_response

router = APIRouter(tags=["retrieval"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    message: str = Field(default="success")
    data: object = Field(default=None)


async def get_knowledge_service_dep(session: AsyncSession = Depends(get_session)) -> KnowledgeBackend:
    return await _get_knowledge_service(session)


@router.post(
    "/retrieval",
    response_model=ApiResponse,
    summary="检索测试（RAGFlow 路径别名）",
)
async def retrieval_alias(
    body: RetrievalRequest = Body(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    """
    与 ``POST /v1/knowledge/retrieval`` 相同。

    参照 https://ragflow.io/docs/http_api_reference 中 Retrieve chunks 接口。
    """
    return ApiResponse(data=build_retrieval_response(service, body))


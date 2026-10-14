"""RAGFlow-compatible document chunk routes (list / enable / disable)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes.knowledge import ApiResponse, get_knowledge_service_dep
from app.schemas.knowledge import (
    KnowledgeFileChunkListResponse,
    SwitchKnowledgeChunksRequest,
    UpdateKnowledgeChunkRequest,
)
from app.services import knowledge_chunk_service
from app.services.knowledge_factory import KnowledgeBackend

router = APIRouter(prefix="/datasets", tags=["document-chunks"])


@router.get(
    "/{dataset_id}/documents/{document_id}/chunks",
    response_model=ApiResponse,
    summary="列出文档切片（含 available 启用状态）",
)
async def list_document_chunks(
    dataset_id: str,
    document_id: str,
    page: int = 1,
    page_size: int = 100,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = knowledge_chunk_service.list_file_chunks(
        service,
        dataset_id,
        document_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(
        data=KnowledgeFileChunkListResponse.model_validate(data).model_dump(mode="json")
    )


@router.patch(
    "/{dataset_id}/documents/{document_id}/chunks/{chunk_id}",
    response_model=ApiResponse,
    summary="启用或停用单个切片",
)
async def update_document_chunk(
    dataset_id: str,
    document_id: str,
    chunk_id: str,
    body: UpdateKnowledgeChunkRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = knowledge_chunk_service.update_chunk_available(
        service,
        dataset_id,
        document_id,
        chunk_id,
        body.available,
    )
    return ApiResponse(data=data)


@router.patch(
    "/{dataset_id}/documents/{document_id}/chunks",
    response_model=ApiResponse,
    summary="批量启用或停用切片",
)
async def switch_document_chunks(
    dataset_id: str,
    document_id: str,
    body: SwitchKnowledgeChunksRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = knowledge_chunk_service.switch_chunks_available(
        service,
        dataset_id,
        document_id,
        body.chunk_ids,
        body.available,
    )
    return ApiResponse(data=data)

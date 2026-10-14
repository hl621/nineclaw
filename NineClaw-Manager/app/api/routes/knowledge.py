"""Knowledge base (RAG) registry routes.

Pure filesystem storage under ``settings.knowledge_storage_path`` —
same pattern as :mod:`app.api.routes.skills`. No external upstream.
"""

from __future__ import annotations

import logging
import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.parse_documents_handler import parse_documents_json_response
from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.external_knowledge_config import ExternalKnowledgeConfig
from app.models.instance import ServiceInstance
from app.schemas.dataset import ParseDocumentsRequest
from app.schemas.knowledge import (
    CreateKnowledgeRequest,
    KnowledgeDeployRequest,
    KnowledgeDetailResponse,
    KnowledgeFileChunkListResponse,
    KnowledgeFileListResponse,
    KnowledgeQARequest,
    KnowledgeResponse,
    RecallRequest,
    RecallResponse,
    SwitchKnowledgeChunksRequest,
    UpdateKnowledgeChunkRequest,
    UpdateKnowledgeRequest,
)
from app.services import knowledge_chunk_service
from app.schemas.retrieval import RetrievalKbRequest, RetrievalRequest
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.instance_agent_snapshot import persist_manager_resource_snapshot
from app.services.knowledge_llm_service import (
    QaLlmError,
    resolve_qa_llm_with_db_fallback,
)
from app.services.knowledge_assistant_runtime import (
    LEGACY_SSE_HEADERS,
    knowledge_assistant_qa_service,
)
from app.services.knowledge_retrieval_service import (
    build_retrieval_response,
    retrieve_chunks,
)
from app.services.knowledge_factory import KnowledgeBackend, _get_knowledge_service
from app.services.external_call_guard import (
    ExternalCallBusyError,
    dependency_busy_http_error,
    external_call_guard,
)
from app.services.knowledge_deploy_service import (
    ENV_QYRAG_DATASETS,
    build_rag_deploy_env,
    resolve_ragflow_credentials,
    rewrite_hermes_dotenv_var_utf8,
)
from app.services.nineclaw_bootstrap import build_dashboard_base_url
from app.services.ragflow_knowledge_service import RagflowKnowledgeService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
)


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    return x_tenant_id or settings.default_tenant_id


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    message: str = Field(default="success")
    data: Any = Field(default=None)


async def get_knowledge_service_dep(
    session: AsyncSession = Depends(get_session),
) -> KnowledgeBackend:
    return await _get_knowledge_service(session)


async def run_knowledge_sync(service: KnowledgeBackend, func, *args, **kwargs):
    if isinstance(service, RagflowKnowledgeService):
        try:
            return await external_call_guard.run_sync("ragflow", func, *args, **kwargs)
        except ExternalCallBusyError as exc:
            raise dependency_busy_http_error(exc) from exc
    return func(*args, **kwargs)


@router.get("/debug/raw-docs/{kb_id}", summary="[调试] 返回 RAGFlow 原始文档字段")
async def debug_raw_docs(
    kb_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> dict:
    """临时调试接口：直接返回 RAGFlow list_documents 的原始数据，不经过 _map_document 处理。"""
    from app.services.ragflow_knowledge_service import RagflowKnowledgeService

    if not isinstance(service, RagflowKnowledgeService):
        return {"error": "非 RAGFlow 后端"}
    try:
        docs = await run_knowledge_sync(
            service, service._client.list_all_documents, kb_id
        )
        if docs:
            sample = docs[0]
            return {
                "total_docs": len(docs),
                "first_doc_keys": list(sample.keys()),
                "first_doc_sample": {
                    k: sample.get(k)
                    for k in [
                        "id",
                        "name",
                        "run",
                        "chunk_count",
                        "chunk_num",
                        "status",
                        "progress",
                        "size",
                    ]
                },
                "all_docs_chunk_info": [
                    {
                        "name": d.get("name"),
                        "run": d.get("run"),
                        "chunk_count": d.get("chunk_count"),
                        "chunk_num": d.get("chunk_num"),
                    }
                    for d in docs
                ],
            }
        return {"total_docs": 0, "docs": []}
    except Exception as exc:
        return {"error": str(exc)}


@router.get(
    "/debug/raw-chunks/{kb_id}/{file_id}", summary="[调试] 返回 RAGFlow 原始切片数据"
)
async def debug_raw_chunks(
    kb_id: str,
    file_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> dict:
    """临时调试接口：直接返回 RAGFlow list_document_chunks 原始数据。"""
    from app.services.ragflow_knowledge_service import RagflowKnowledgeService

    if not isinstance(service, RagflowKnowledgeService):
        return {"error": "非 RAGFlow 后端"}
    try:
        data = await run_knowledge_sync(
            service,
            service._client.list_document_chunks,
            kb_id,
            file_id,
            page=1,
            page_size=5,
        )
        result: dict = {"data_type": type(data).__name__}
        if isinstance(data, dict):
            result["top_level_keys"] = list(data.keys())
            doc = data.get("doc")
            if isinstance(doc, dict):
                result["doc_keys"] = list(doc.keys())
                result["doc_chunk_count"] = doc.get("chunk_count")
                result["doc_chunk_num"] = doc.get("chunk_num")
            chunks = data.get("chunks", [])
            result["chunks_count"] = len(chunks) if isinstance(chunks, list) else 0
            result["total"] = data.get("total")
            if isinstance(chunks, list) and chunks:
                result["first_chunk_keys"] = (
                    list(chunks[0].keys()) if isinstance(chunks[0], dict) else []
                )
        return result
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/images/{image_id}", summary="切片图片代理（RAGFlow 视觉解析图）")
async def get_chunk_image(
    image_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> Response:
    """代理 RAGFlow ``GET /api/v1/documents/images/<image_id>``。

    image_id 即切片 ``image_id`` 字段（``{dataset_id}-{object_key}``），
    仅允许十六进制+连字符，避免任意路径透传。
    """

    import re

    from app.services.ragflow_client import RagflowError
    from app.services.ragflow_knowledge_service import RagflowKnowledgeService

    if not re.fullmatch(r"[0-9a-fA-F]{8,64}-[0-9a-fA-F]{4,64}", image_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="非法 image_id"
        )
    if not isinstance(service, RagflowKnowledgeService):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅 RAGFlow 知识库后端支持切片图片",
        )
    try:
        content, content_type = await run_knowledge_sync(
            service, service._client.get_document_image, image_id
        )
    except RagflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        logger.exception("fetch chunk image failed: %s", image_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"获取切片图片失败：{exc}",
        ) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("", response_model=ApiResponse, summary="List knowledge bases")
async def list_knowledge(
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    try:
        records = await run_knowledge_sync(service, service.list_knowledge)
    except Exception as exc:
        logger.exception(
            "list knowledge failed (backend=%s)", settings.knowledge_backend
        )
        if isinstance(exc, HTTPException):
            raise
        detail = str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"加载知识库失败：{detail}",
        ) from exc

    items = [
        KnowledgeResponse.model_validate(record).model_dump(mode="json")
        for record in records
    ]
    return ApiResponse(
        data={
            "items": items,
            "total": len(items),
        }
    )


@router.post(
    "",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge base",
)
async def create_knowledge(
    body: CreateKnowledgeRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    name = (body.name or "").strip()
    if name:
        try:
            existing = await run_knowledge_sync(service, service.list_knowledge)
        except Exception:
            logger.exception("create_knowledge: pre-check list_knowledge failed")
            existing = []
        if any(str(item.get("name", "")).strip() == name for item in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"知识库 '{name}' 已存在",
            )
    record = await run_knowledge_sync(service, service.create_knowledge, body)
    return ApiResponse(
        data=KnowledgeResponse.model_validate(record).model_dump(mode="json")
    )


@router.post(
    "/{kb_id}/reindex",
    response_model=ApiResponse,
    summary="Re-scan documents and refresh index status",
)
async def reindex_knowledge(
    kb_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    record = await run_knowledge_sync(service, service.reindex, kb_id)
    return ApiResponse(
        data=KnowledgeResponse.model_validate(record).model_dump(mode="json")
    )


@router.post(
    "/{kb_id}/chunks",
    summary="解析文档（RAGFlow 兼容，同 /v1/datasets/{kb_id}/chunks）",
    response_model=None,
)
async def parse_knowledge_documents(
    kb_id: str,
    body: ParseDocumentsRequest = Body(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
):
    """
    解析知识库内指定文档，请求/响应与 RAGFlow Parse documents 一致。

    ``dataset_id`` 即知识库 ``kb_id``；``document_ids`` 为上传接口返回的文件 ``id``。
    """
    return await run_knowledge_sync(
        service,
        parse_documents_json_response,
        service,
        kb_id,
        body.document_ids,
    )


@router.post(
    "/{kb_id}/files",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document into a knowledge base",
)
async def upload_file(
    kb_id: str,
    file: UploadFile = File(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    content = await file.read()
    record = await run_knowledge_sync(
        service,
        service.upload_file,
        kb_id,
        file.filename or "upload.bin",
        content,
    )
    return ApiResponse(data=record)


@router.get(
    "/{kb_id}/files",
    response_model=ApiResponse,
    summary="List documents in a knowledge base",
)
async def list_files(
    kb_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    q: str | None = Query(default=None),
    keywords: str | None = Query(default=None),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = await run_knowledge_sync(
        service,
        service.list_files,
        kb_id,
        page=page,
        page_size=page_size,
        keywords=(keywords or q or None),
    )
    return ApiResponse(
        data=KnowledgeFileListResponse.model_validate(data).model_dump(mode="json")
    )


@router.get(
    "/{kb_id}/files/{file_id}/preview",
    response_model=ApiResponse,
    summary="Preview document text (txt/md/docx etc.)",
)
async def preview_file(
    kb_id: str,
    file_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = await run_knowledge_sync(
        service, service.get_file_preview_text, kb_id, file_id
    )
    return ApiResponse(data=data)


@router.get(
    "/{kb_id}/files/{file_id}/media-content",
    response_model=ApiResponse,
    summary="Get audio/video content via RAGFlow chunks or tenant ASR",
)
async def get_media_content(
    kb_id: str,
    file_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    if not isinstance(service, RagflowKnowledgeService):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="音视频转写需要 RAGFlow 知识库后端",
        )
    from app.services.knowledge_service import KnowledgeError

    try:
        data = await run_knowledge_sync(
            service, service.get_media_content, kb_id, file_id
        )
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ApiResponse(data=data)


@router.post(
    "/{kb_id}/files/{file_id}/media-transcribe",
    response_model=ApiResponse,
    summary="Transcribe uploaded audio track via RAGFlow default ASR",
)
async def media_transcribe(
    kb_id: str,
    file_id: str,
    file: UploadFile = File(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    """前端切段音轨上传，仅走 RAGFlow 默认 ASR。"""
    if not isinstance(service, RagflowKnowledgeService):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="音视频转写需要 RAGFlow 知识库后端",
        )
    from app.services.knowledge_service import KnowledgeError

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="空音频文件",
        )
    try:
        data = await run_knowledge_sync(
            service,
            service.transcribe_uploaded_audio,
            kb_id,
            file_id,
            file.filename or "audio.webm",
            content,
        )
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ApiResponse(data=data)


@router.get(
    "/{kb_id}/files/{file_id}/chunks",
    response_model=ApiResponse,
    summary="List parsed chunks for a document",
)
async def list_file_chunks(
    kb_id: str,
    file_id: str,
    page: int = 1,
    page_size: int = 100,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = await run_knowledge_sync(
        service,
        knowledge_chunk_service.list_file_chunks,
        service,
        kb_id,
        file_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(
        data=KnowledgeFileChunkListResponse.model_validate(data).model_dump(mode="json")
    )


@router.patch(
    "/{kb_id}/files/{file_id}/chunks",
    response_model=ApiResponse,
    summary="批量启用或停用文档切片",
)
async def switch_file_chunks(
    kb_id: str,
    file_id: str,
    body: SwitchKnowledgeChunksRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = await run_knowledge_sync(
        service,
        knowledge_chunk_service.switch_chunks_available,
        service,
        kb_id,
        file_id,
        body.chunk_ids,
        body.available,
    )
    return ApiResponse(data=data)


@router.patch(
    "/{kb_id}/files/{file_id}/chunks/{chunk_id}",
    response_model=ApiResponse,
    summary="启用或停用单个文档切片",
)
async def update_file_chunk(
    kb_id: str,
    file_id: str,
    chunk_id: str,
    body: UpdateKnowledgeChunkRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    data = await run_knowledge_sync(
        service,
        knowledge_chunk_service.update_chunk_available,
        service,
        kb_id,
        file_id,
        chunk_id,
        body.available,
    )
    return ApiResponse(data=data)


@router.get(
    "/{kb_id}/files/{file_id}/download",
    summary="Download a document from a knowledge base",
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Raw file bytes with Content-Disposition attachment.",
        }
    },
)
async def download_file(
    kb_id: str,
    file_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> FileResponse:
    path, filename, media_type = await run_knowledge_sync(
        service,
        service.get_file_for_download,
        kb_id,
        file_id,
    )
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,
    )


@router.delete(
    "/{kb_id}/files/{file_id}",
    response_model=ApiResponse,
    summary="Delete a document from a knowledge base",
)
async def delete_file(
    kb_id: str,
    file_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    await run_knowledge_sync(service, service.delete_file, kb_id, file_id)
    return ApiResponse(data={"deleted": file_id})


@router.get(
    "/qa/model",
    response_model=ApiResponse,
    summary="知识问答默认大模型（供前端展示）",
)
async def knowledge_qa_model_info(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """返回模型管理中可用于知识问答的默认模型。"""
    try:
        llm = await resolve_qa_llm_with_db_fallback(session, tenant_id, None, None)
        return ApiResponse(
            data={
                "configured": True,
                "model": llm.model,
                "provider": llm.provider_name,
            }
        )
    except QaLlmError:
        return ApiResponse(
            data={"configured": False, "model": None, "provider": None},
        )


@router.post(
    "/qa",
    summary="知识问答（SSE 流式）",
    response_class=StreamingResponse,
)
async def knowledge_qa(
    request: KnowledgeQARequest = Body(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    """
    知识问答接口（SSE 流式输出）：AgenticRAG（与详情页 Studio 同 Agent）。

    可在一个或多个知识库范围内检索并生成回答；内部可多轮工具调用
    （rag_retrieve / rag_check_sufficient_context 等），对外仍输出兼容
    全局检索页的 legacy SSE。

    请求体::

        {
            "question": "用户问题",
            "dataset_ids": ["数据集ID1", "数据集ID2"],
            "top_k": 5
        }

    返回格式（SSE）::

        data: {"type": "references", "references": [...]}
        data: {"type": "content", "content": "回答文本"}
        data: [DONE]
    """
    try:
        llm = await resolve_qa_llm_with_db_fallback(
            session,
            tenant_id,
            request.provider_id,
            request.model,
        )
    except QaLlmError:
        llm = None

    return StreamingResponse(
        knowledge_assistant_qa_service(
            service=service,
            question=request.question,
            dataset_ids=request.dataset_ids,
            top_k=request.top_k,
            rerank_id=request.rerank_id,
            tenant_rerank_id=request.tenant_rerank_id,
            temperature=request.temperature,
            enable_thinking=request.enable_thinking,
            llm=llm,
        ),
        media_type="text/event-stream",
        headers=LEGACY_SSE_HEADERS,
    )


async def _run_retrieval(
    service: KnowledgeBackend,
    body: RetrievalRequest,
) -> ApiResponse:
    try:
        data = await run_knowledge_sync(
            service,
            build_retrieval_response,
            service,
            body,
        )
        return ApiResponse(data=data)
    except Exception as exc:
        logger.exception("knowledge retrieval failed: %s", body.question)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"检索失败：{exc}",
        ) from exc


@router.post(
    "/retrieval",
    response_model=ApiResponse,
    summary="检索测试（RAGFlow 兼容）",
)
async def knowledge_retrieval(
    body: RetrievalRequest = Body(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    """
    检索测试接口，参照 RAGFlow ``POST /api/v1/retrieval``。

    请求体示例::

        {
            "question": "如何重置密码？",
            "dataset_ids": ["kb-id"],
            "document_ids": [],
            "page": 1,
            "page_size": 30,
            "similarity_threshold": 0.2,
            "vector_similarity_weight": 0.3,
            "keyword": false,
            "highlight": true
        }

    响应 ``data`` 字段含 ``chunks``、``doc_aggs``、``total``。
    """
    return await _run_retrieval(service, body)


@router.post(
    "/{kb_id}/retrieval",
    response_model=ApiResponse,
    summary="单库检索测试（RAGFlow 兼容）",
)
async def knowledge_retrieval_kb(
    kb_id: str,
    body: RetrievalKbRequest = Body(...),
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    """``POST /v1/knowledge/{kb_id}/retrieval`` — dataset_ids 固定为路径中的知识库 ID。"""
    return await _run_retrieval(service, body.to_retrieval_request(kb_id))


@router.post(
    "/{kb_id}/recall",
    response_model=ApiResponse,
    summary="单库召回测试（兼容旧接口）",
)
async def knowledge_recall(
    kb_id: str,
    body: RecallRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    """兼容 ``POST /v1/knowledge/{kb_id}/recall``，内部走 RAGFlow 检索逻辑。"""
    request = RetrievalRequest(
        question=body.query,
        dataset_ids=[kb_id],
        page_size=10,
        similarity_threshold=body.similarity,
        vector_similarity_weight=body.vector_weight,
        keyword=True,
        highlight=True,
    )
    result = await run_knowledge_sync(
        service,
        retrieve_chunks,
        service,
        request,
    )
    legacy_chunks = [
        {
            "chunk_id": c["id"],
            "document_id": c.get("document_id"),
            "text": c["content"],
            "score": c["similarity"],
            "file_name": c.get("document_keyword"),
            "available": c.get("available", True),
        }
        for c in result.get("chunks", [])
    ]
    return ApiResponse(
        data=RecallResponse.model_validate({"chunks": legacy_chunks}).model_dump(
            mode="json"
        )
    )


# ─── Deploy ───────────────────────────────────────────────────────────────────

_DEPLOY_RESTART_TIMEOUT = 60.0


def _display_name_from_knowledge_record(record: Any, fallback: str) -> str:
    if isinstance(record, dict):
        name = record.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return fallback


@router.post(
    "/deploy",
    summary="流式将知识库配置部署到 NineClaw 实例（SSE）",
)
async def deploy_knowledge(
    request: Request,
    body: KnowledgeDeployRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """将选中的知识库配置（knowledge_ids + 外部知识库接口信息）写入每个目标实例的
    Hermes 配置中，通过 SSE 流式返回每个实例的部署进度。

    Hermes 配置写入字段示例::

        external_knowledge:
          base_url: <ragflow_base_url>
          api_key: <ragflow_api_key>
          dataset_ids: ["id1", "id2"]
    """
    # Pre-validate: fetch RAGFlow config and instances from DB
    async with async_session_maker() as session:
        # Read external knowledge config (RAGFlow base_url + api_key)
        ext_cfg = await session.scalar(
            select(ExternalKnowledgeConfig).where(
                ExternalKnowledgeConfig.tenant_id == tenant_id
            )
        )

        # Read target instances
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

        knowledge_service = await _get_knowledge_service(session)
        knowledge_name_map: dict[str, str] = {}
        client_names = {
            str(kid).strip(): str(name).strip()
            for kid, name in (body.knowledge_names or {}).items()
            if str(kid).strip() and isinstance(name, str) and str(name).strip()
        }
        knowledge_records_by_id: dict[str, dict[str, Any]] = {}
        try:
            for record in await run_knowledge_sync(
                knowledge_service,
                knowledge_service.list_knowledge,
            ):
                if not isinstance(record, dict):
                    continue
                for key in (record.get("id"), record.get("dataset_id")):
                    rid = str(key or "").strip()
                    if rid:
                        knowledge_records_by_id[rid] = record
        except Exception as exc:
            logger.warning(
                "deploy knowledge: failed to list knowledge names: %s",
                exc,
            )
        for knowledge_id in body.knowledge_ids:
            kid = str(knowledge_id or "").strip()
            if not kid:
                continue
            if kid in client_names:
                knowledge_name_map[kid] = client_names[kid]
                continue
            record = knowledge_records_by_id.get(kid)
            if record is None:
                try:
                    record = await run_knowledge_sync(
                        knowledge_service,
                        knowledge_service.get_knowledge,
                        kid,
                    )
                except Exception as exc:
                    logger.warning(
                        "deploy knowledge: failed to resolve name for %s: %s",
                        kid,
                        exc,
                    )
            knowledge_name_map[kid] = _display_name_from_knowledge_record(
                record,
                kid,
            )

    rag_base_url, rag_api_key = resolve_ragflow_credentials(
        base_url=ext_cfg.base_url if ext_cfg else None,
        api_key=ext_cfg.api_key if ext_cfg else None,
    )

    # Build external_knowledge config block
    dataset_ids = [str(kid).strip() for kid in body.knowledge_ids if str(kid).strip()]
    ext_knowledge_block: dict = {
        "dataset_ids": dataset_ids,
    }
    if rag_base_url:
        ext_knowledge_block["base_url"] = rag_base_url
    if rag_api_key:
        ext_knowledge_block["api_key"] = rag_api_key

    qyrag_env = build_rag_deploy_env(
        base_url=rag_base_url,
        api_key=rag_api_key,
        knowledge_ids=dataset_ids,
        knowledge_name_map=knowledge_name_map,
    )

    # Preserve user order
    inst_by_id = {i.id: i for i in instances}
    seen: set[str] = set()
    ordered_instances: list[Any] = []
    for iid in body.instance_ids:
        if iid not in seen and iid in inst_by_id:
            seen.add(iid)
            ordered_instances.append(inst_by_id[iid])

    api_key = settings.nineclaw_token

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        # Initial pending snapshot
        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {"instance_id": inst.id, "status": "pending", "error": None}
                ),
            }

        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {"instance_id": inst.id, "status": "deploying", "error": None}
                ),
            }

            actual = (inst.actual_state or "").lower()
            if actual != "running":
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "status": "failed",
                            "error": (
                                f"实例当前状态为 {actual or 'unknown'}，"
                                "必须运行中才能部署"
                            ),
                        }
                    ),
                }
                continue

            base_url = build_dashboard_base_url(inst.id)
            try:
                async with HermesService(base_url=base_url, api_key=api_key) as svc:
                    current = await svc.get_config()
                    if not isinstance(current, dict):
                        current = {}

                    # Merge: preserve existing config, only update external_knowledge
                    current["external_knowledge"] = ext_knowledge_block
                    await svc.put_config(current)

                    for key, value in qyrag_env.items():
                        # Hermes PUT /api/env strips non-ASCII → empty JSON keys.
                        # Put an ASCII-safe form first so .env never stays as {"": id}.
                        put_value = value
                        if key == ENV_QYRAG_DATASETS:
                            try:
                                put_value = json.dumps(
                                    json.loads(value), ensure_ascii=True
                                )
                            except (TypeError, ValueError):
                                put_value = value
                        await svc.put_env(key, put_value)

                    # Rewrite QYRAG_DATASETS as UTF-8 Chinese via Docker so
                    # `cat /opt/data/.env` shows {"策略分析": "..."} not \uXXXX.
                    datasets_value = qyrag_env.get(ENV_QYRAG_DATASETS)
                    docker_service = getattr(
                        request.app.state, "docker_service", None
                    )
                    if (
                        datasets_value
                        and docker_service is not None
                        and (inst.container_id or "").strip()
                    ):
                        try:
                            await rewrite_hermes_dotenv_var_utf8(
                                docker_service,
                                inst.container_id,
                                ENV_QYRAG_DATASETS,
                                datasets_value,
                            )
                        except Exception as rewrite_exc:
                            logger.warning(
                                "deploy knowledge: utf-8 dotenv rewrite failed for %s: %s "
                                "(ASCII-safe QYRAG_DATASETS already written via Hermes)",
                                inst.id,
                                rewrite_exc,
                            )

                    # Restart gateway so new knowledge config takes effect
                    restart_result = await svc.restart_gateway()
                    action_name = "gateway-restart"
                    if isinstance(restart_result, dict) and restart_result.get("name"):
                        action_name = str(restart_result["name"])
                    action_status = await svc.wait_action_finished(
                        action_name,
                        timeout=_DEPLOY_RESTART_TIMEOUT,
                    )
                    if isinstance(action_status, dict) and action_status.get(
                        "exit_code"
                    ) not in (0, None):
                        exit_code = action_status.get("exit_code")
                        raise RuntimeError(f"Gateway 重启失败 (exit_code={exit_code})")
                async with async_session_maker() as snapshot_session:
                    await persist_manager_resource_snapshot(
                        snapshot_session,
                        tenant_id=tenant_id,
                        instance_id=inst.id,
                        knowledge_bases=[
                            {
                                "id": knowledge_id,
                                "name": knowledge_name_map[knowledge_id],
                            }
                            for knowledge_id in body.knowledge_ids
                        ],
                    )
                    await snapshot_session.commit()

            except HermesError as exc:
                logger.warning(
                    "deploy knowledge: hermes error for %s: %s", inst.id, exc.detail
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "status": "failed",
                            "error": f"Hermes {exc.status_code}: {exc.detail}",
                        }
                    ),
                }
                continue
            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "deploy knowledge: connection error for %s: %s", inst.id, exc
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "status": "failed",
                            "error": f"无法连接实例: {exc.__class__.__name__}",
                        }
                    ),
                }
                continue
            except Exception as exc:
                logger.exception("deploy knowledge: unexpected error for %s", inst.id)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "status": "failed",
                            "error": str(exc),
                        }
                    ),
                }
                continue

            yield {
                "event": "status",
                "data": json.dumps(
                    {"instance_id": inst.id, "status": "deployed", "error": None}
                ),
            }

        yield {"event": "done", "data": json.dumps({"finished": True})}

    return EventSourceResponse(event_stream())


@router.get(
    "/{kb_id}",
    response_model=ApiResponse,
    summary="Get knowledge base metadata and files",
)
async def get_knowledge(
    kb_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    try:
        record = await run_knowledge_sync(service, service.get_knowledge, kb_id)
        data = KnowledgeDetailResponse.model_validate(record).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get knowledge failed: %s", kb_id)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"加载知识库失败：{exc}",
        ) from exc
    return ApiResponse(data=data)


@router.put(
    "/{kb_id}",
    response_model=ApiResponse,
    summary="Update knowledge base metadata",
)
async def update_knowledge(
    kb_id: str,
    body: UpdateKnowledgeRequest,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    record = await run_knowledge_sync(service, service.update_knowledge, kb_id, body)
    return ApiResponse(
        data=KnowledgeResponse.model_validate(record).model_dump(mode="json")
    )


@router.delete(
    "/{kb_id}",
    response_model=ApiResponse,
    summary="Delete a knowledge base from disk",
)
async def delete_knowledge(
    kb_id: str,
    service: KnowledgeBackend = Depends(get_knowledge_service_dep),
) -> ApiResponse:
    deleted = await run_knowledge_sync(service, service.delete_knowledge, kb_id)
    return ApiResponse(data={"deleted": deleted})

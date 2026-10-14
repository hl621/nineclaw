"""文档切片：列表查询与启用/停用（RAGFlow ``available`` 字段）。"""

from __future__ import annotations

from typing import Any

import logging

from fastapi import status

from app.core.config import settings
from app.services.chunk_availability import parse_chunk_available
from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_service import KnowledgeError, KnowledgeService
from app.services.ragflow_client import RagflowClient, RagflowError, get_ragflow_client
from app.services.ragflow_knowledge_service import _ragflow_to_http_error

logger = logging.getLogger(__name__)


def extract_chunk_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        nested_data = data.get("data")
        candidates: list[Any] = []
        if isinstance(data.get("chunks"), list):
            candidates = data["chunks"]
        elif isinstance(nested_data, dict) and isinstance(
            nested_data.get("chunks"), list
        ):
            candidates = nested_data["chunks"]
        elif isinstance(nested_data, list):
            candidates = nested_data
        elif isinstance(data.get("items"), list):
            candidates = data["items"]
        return [item for item in candidates if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def map_chunk_item(ck: dict[str, Any]) -> dict[str, Any]:
    chunk_id = str(ck.get("id") or ck.get("chunk_id") or "")
    return {
        "id": chunk_id,
        "content": str(
            ck.get("content")
            or ck.get("content_with_weight")
            or ck.get("content_ltks")
            or ck.get("text")
            or ck.get("question")
            or ck.get("answer")
            or ""
        ).strip(),
        "available": parse_chunk_available(ck),
        "important_keywords": ck.get("important_keywords")
        or ck.get("important_kwd")
        or [],
        # 视觉解析切片带的图片引用（{dataset_id}-{object_key}），前端据此渲染图片
        "image_id": str(ck.get("image_id") or ""),
        "synthetic": bool(ck.get("synthetic")),
    }


def _chunks_from_preview_text(
    service: KnowledgeBackend,
    kb_id: str,
    file_id: str,
    *,
    page: int,
    page_size: int,
) -> dict[str, Any] | None:
    """RAGFlow 向量索引无切片时，用预览文本分段（仅供展示与关键词问答回退）。"""
    from app.services.knowledge_service import _split_preview_chunks
    from app.services.ragflow_knowledge_service import RagflowKnowledgeService

    if not isinstance(service, RagflowKnowledgeService):
        return None
    try:
        preview = service.get_file_preview_text(kb_id, file_id)
        text = str(preview.get("text") or "").strip()
    except Exception:
        return None
    if not text:
        return None

    blocks = [b.strip() for b in _split_preview_chunks(text) if b.strip()]
    if not blocks:
        return None
    start = (page - 1) * page_size
    page_blocks = blocks[start : start + page_size]
    chunks = [
        {
            "id": f"{file_id}#preview-{start + i}",
            "content": block,
            "available": True,
            "important_keywords": [],
            "synthetic": True,
        }
        for i, block in enumerate(page_blocks)
    ]
    return {
        "chunks": chunks,
        "total": len(blocks),
        "synthetic": True,
    }


def list_file_chunks_ragflow(
    client: RagflowClient,
    kb_id: str,
    file_id: str,
    *,
    page: int = 1,
    page_size: int = 100,
    service: KnowledgeBackend | None = None,
) -> dict[str, Any]:
    try:
        data = client.list_document_chunks(
            kb_id, file_id, page=page, page_size=max(page_size, 100)
        )
    except RagflowError as exc:
        raise _ragflow_to_http_error(exc) from exc

    logger.info(
        "[RAGFlow chunks] kb=%s file=%s data_type=%s data_keys=%s",
        kb_id,
        file_id,
        type(data).__name__,
        list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]",
    )

    raw = extract_chunk_list(data)
    chunks: list[dict[str, Any]] = []
    for i, ck in enumerate(raw):
        item = map_chunk_item(ck)
        if not item["id"] and item["content"]:
            item["id"] = f"{file_id}#rag-{page}-{i}"
        if item["id"] and item["content"]:
            chunks.append(item)
    total = len(chunks)
    if isinstance(data, dict):
        doc = data.get("doc")
        if isinstance(doc, dict):
            # RAGFlow HTTP API: doc.chunk_num 或 doc.chunk_count
            cnt = doc.get("chunk_count") or doc.get("chunk_num")
            if cnt is not None:
                total = int(cnt)
        elif data.get("total") is not None:
            total = int(data["total"])
    logger.info(
        "[RAGFlow chunks] kb=%s file=%s raw_count=%d total=%d",
        kb_id, file_id, len(chunks), total,
    )

    if chunks:
        return {"chunks": chunks, "total": total, "synthetic": False}

    if service is not None:
        fallback = _chunks_from_preview_text(
            service, kb_id, file_id, page=page, page_size=page_size
        )
        if fallback:
            return fallback

    return {"chunks": [], "total": total, "synthetic": False}


def update_chunk_available_ragflow(
    client: RagflowClient,
    kb_id: str,
    file_id: str,
    chunk_id: str,
    available: bool,
) -> dict[str, Any]:
    try:
        # RAGFlow 单切片 PATCH 用于编辑内容，切换 available 须用批量接口
        client.switch_document_chunks(
            kb_id,
            file_id,
            [chunk_id],
            available=available,
        )
    except RagflowError as exc:
        raise _ragflow_to_http_error(exc) from exc

    return {"chunk_id": chunk_id, "available": available}


def switch_chunks_available_ragflow(
    client: RagflowClient,
    kb_id: str,
    file_id: str,
    chunk_ids: list[str],
    available: bool,
) -> dict[str, Any]:
    if not chunk_ids:
        raise KnowledgeError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chunk_ids 不能为空",
        )
    try:
        data = client.switch_document_chunks(
            kb_id, file_id, chunk_ids, available=available
        )
    except RagflowError as exc:
        raise _ragflow_to_http_error(exc) from exc

    return {
        "chunk_ids": chunk_ids,
        "available": available,
        "updated": len(chunk_ids),
        "result": data if isinstance(data, dict) else None,
    }


def _ragflow_client(service: KnowledgeBackend) -> RagflowClient:
    client = getattr(service, "_client", None)
    if isinstance(client, RagflowClient):
        return client
    return get_ragflow_client()


def list_file_chunks(
    service: KnowledgeBackend,
    kb_id: str,
    file_id: str,
    *,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """列出文档下所有切片（含 ``available`` 启用状态）。"""
    service.ensure_exists(kb_id)
    from app.services.ragflow_knowledge_service import RagflowKnowledgeService

    if settings.knowledge_backend == "ragflow" or isinstance(
        service, RagflowKnowledgeService
    ):
        return list_file_chunks_ragflow(
            _ragflow_client(service),
            kb_id,
            file_id,
            page=page,
            page_size=page_size,
            service=service,
        )
    if isinstance(service, KnowledgeService):
        return service.list_file_chunks(
            kb_id, file_id, page=page, page_size=page_size
        )
    return {"chunks": [], "total": 0}


def update_chunk_available(
    service: KnowledgeBackend,
    kb_id: str,
    file_id: str,
    chunk_id: str,
    available: bool,
) -> dict[str, Any]:
    """启用或停用单个切片（``available``: true / false）。"""
    service.ensure_exists(kb_id)
    if settings.knowledge_backend == "ragflow":
        return update_chunk_available_ragflow(
            _ragflow_client(service), kb_id, file_id, chunk_id, available
        )
    if isinstance(service, KnowledgeService):
        return service.set_chunk_available(kb_id, file_id, chunk_id, available)
    raise KnowledgeError(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="当前知识库后端不支持切片启用/停用",
    )


def switch_chunks_available(
    service: KnowledgeBackend,
    kb_id: str,
    file_id: str,
    chunk_ids: list[str],
    available: bool,
) -> dict[str, Any]:
    """批量启用或停用多个切片。"""
    service.ensure_exists(kb_id)
    if settings.knowledge_backend == "ragflow":
        return switch_chunks_available_ragflow(
            _ragflow_client(service), kb_id, file_id, chunk_ids, available
        )
    raise KnowledgeError(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="本地文件模式暂不支持批量切换切片状态",
    )

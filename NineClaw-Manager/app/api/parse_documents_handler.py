"""Shared handler for RAGFlow ``POST .../datasets/{id}/chunks`` parse documents."""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_service import KnowledgeError

logger = logging.getLogger(__name__)


def parse_documents_json_response(
    service: KnowledgeBackend,
    dataset_id: str,
    document_ids: list[str],
) -> JSONResponse:
    """
    Parse documents in a dataset (knowledge base).

    Success: ``{"code": 0}`` — matches RAGFlow Parse documents API.
    """
    if not document_ids:
        return JSONResponse(
            status_code=200,
            content={"code": 102, "message": "`document_ids` is required"},
        )

    try:
        service.parse_documents(dataset_id, document_ids)
    except KnowledgeError as exc:
        logger.warning(
            "parse documents failed for dataset %s: %s",
            dataset_id,
            exc.detail,
        )
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={"code": 102, "message": str(exc.detail)},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": 102, "message": str(exc.detail)},
        )
    except Exception as exc:
        logger.exception("parse documents failed for dataset %s", dataset_id)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": f"解析失败：{exc}"},
        )

    return JSONResponse(status_code=200, content={"code": 0})

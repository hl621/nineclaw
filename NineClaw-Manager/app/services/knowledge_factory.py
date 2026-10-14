"""Factory for knowledge backend — async FastAPI dependency."""

from __future__ import annotations

from typing import Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.external_knowledge_config import ExternalKnowledgeConfig
from app.services.knowledge_service import KnowledgeError, KnowledgeService
from app.services.ragflow_client import RagflowClient, RagflowError, set_ragflow_client
from app.services.ragflow_knowledge_service import RagflowKnowledgeService

KnowledgeBackend = Union[KnowledgeService, RagflowKnowledgeService]

# filesystem backend is stateless — reuse one instance
_fs_singleton: KnowledgeService | None = None


async def get_knowledge_service(
    session: AsyncSession = get_session,  # resolved below via Depends
) -> KnowledgeBackend:
    raise NotImplementedError  # replaced by the Depends version below


async def _get_knowledge_service(session: AsyncSession) -> KnowledgeBackend:
    """Resolve knowledge backend from DB config (per-tenant) or .env fallback."""
    row = await session.scalar(
        select(ExternalKnowledgeConfig).where(
            ExternalKnowledgeConfig.tenant_id == settings.default_tenant_id
        )
    )

    if row and row.base_url:
        backend, base_url, api_key = row.backend, row.base_url, row.api_key
    else:
        backend = settings.knowledge_backend
        base_url, api_key = "", ""

    if backend == "ragflow":
        try:
            client = RagflowClient(base_url=base_url, api_key=api_key)
            set_ragflow_client(client)
            return RagflowKnowledgeService(client=client)
        except RagflowError as exc:
            raise KnowledgeError(status_code=502, detail=exc.message) from exc

    global _fs_singleton
    if _fs_singleton is None:
        svc = KnowledgeService(
            storage_root=settings.knowledge_storage_path,
            max_upload_size=settings.knowledge_max_upload_size,
        )
        svc.ensure_storage()
        _fs_singleton = svc
    return _fs_singleton


def reset_knowledge_service() -> None:
    """Clear filesystem singleton (ragflow backend is stateless)."""
    global _fs_singleton
    _fs_singleton = None

"""Model Provider API Routes.

RESTful CRUD for OpenAI-compatible model providers, scoped per tenant via
the ``X-Tenant-ID`` header (same pattern as the nineclaw routes).

Routes:
- GET    /providers              - List providers for the tenant
- POST   /providers              - Create a provider
- GET    /providers/{id}         - Get a provider
- PUT    /providers/{id}         - Update a provider (partial)
- DELETE /providers/{id}         - Delete a provider
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.external_knowledge_config import ExternalKnowledgeConfig
from app.models.instance import ServiceInstance
from app.models.provider import Provider, _utcnow
from app.schemas.provider import (
    DeployAuxModel,
    DeployMainModel,
    DeployRequest,
    FetchModelsRequest,
    FetchModelsResponse,
    ProviderChatCompletionRequest,
    ProviderCreate,
    ProviderEmbeddingRequest,
    ProviderResponse,
    ProviderRerankRequest,
    ProviderSpeechRequest,
    ProviderUpdate,
)
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.instance_agent_snapshot import (
    extract_provider_snapshot_from_hermes_config,
    lock_instance_for_snapshot,
    persist_manager_resource_snapshot,
)
from app.services.moa_adapt_service import adapt_moa_config_to_instance
from app.services.nineclaw_bootstrap import build_dashboard_base_url

logger = logging.getLogger(__name__)

TENANT_HEADER = "X-Tenant-ID"

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
)

models_router = APIRouter(tags=["models"])


def _provider_endpoint(base_url: str, path: str) -> str:
    """Append an API path without guessing or inserting a version prefix."""
    return f"{(base_url or '').rstrip('/')}/{path.lstrip('/')}"


class _SnapshotPersistError(Exception):
    """Internal marker for snapshot persistence failures after Hermes PUT."""


def _build_custom_provider_entry(provider: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": provider.name,
        "base_url": provider.base_url,
        "models": {model: {} for model in (provider.models or [])},
    }
    if provider.models:
        entry["discover_models"] = False
    if provider.api_key:
        entry["api_key"] = provider.api_key
    return entry


def _build_deploy_custom_providers(
    providers: list[Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    name_index: dict[tuple[str, str], dict[str, Any]] = {}
    for provider in providers:
        entries.append(_build_custom_provider_entry(provider))
        for model in provider.models or []:
            name_index[(provider.name, model)] = {
                "provider_name": provider.name,
                "model": model,
                "base_url": provider.base_url,
                "api_key": provider.api_key or "",
            }
    return entries, name_index


class ApiResponse(BaseModel):
    """Standard envelope used across the manager API."""

    code: int = Field(default=0)
    message: str = Field(default="success")
    data: Any = Field(default=None)


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER),
) -> str:
    return x_tenant_id or settings.default_tenant_id


def _infer_model_types(provider_name: str, model_name: str) -> list[str]:
    text = f"{provider_name} {model_name}".lower()
    if "rerank" in text or "reranker" in text or "bge-reranker" in text:
        return ["rerank"]
    if (
        "embed" in text
        or "embedding" in text
        or "bge-" in text
        and "rerank" not in text
    ):
        return ["embedding"]
    # TTS before generic "speech" (MiniMax/speech-* is TTS, not ASR)
    if "tts" in text or "speech-" in text or "/speech" in text:
        return ["tts"]
    if (
        "whisper" in text
        or "asr" in text
        or "speech2text" in text
        or "transcription" in text
        or "speech" in text
    ):
        return ["speech2text"]
    if "vision" in text or "visual" in text or "vl" in text:
        return ["image2text"]
    return ["chat"]


def _extract_supported_auxiliary_tasks(payload: Any) -> set[str]:
    """Return the auxiliary task names supported by a Runtime instance."""
    if not isinstance(payload, dict):
        return set()
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return set()

    supported: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task = item.get("task")
        if isinstance(task, str) and task:
            supported.add(task)
    return supported


def _normalize_ragflow_model(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        model_id = item.strip()
        if not model_id:
            return None
        return {
            "id": model_id,
            "value": model_id,
            "model_type": [],
            "name": model_id,
            "provider_id": "",
            "provider_name": "",
            "instance_id": "",
            "instance_name": "",
            "tenant_model_id": None,
        }
    if not isinstance(item, dict):
        return None
    name = str(
        item.get("name")
        or item.get("model_name")
        or item.get("id")
        or item.get("model")
        or ""
    ).strip()
    if not name:
        return None
    model_id = str(
        item.get("id")
        or item.get("model_id")
        or item.get("model")
        or item.get("name")
        or item.get("model_name")
        or ""
    ).strip()
    raw_types = (
        item.get("model_type") or item.get("model_types") or item.get("type") or []
    )
    if isinstance(raw_types, str):
        model_types = [raw_types]
    elif isinstance(raw_types, list):
        model_types = [str(t) for t in raw_types if t]
    else:
        model_types = []
    provider_name = str(item.get("provider_name") or item.get("provider") or "")
    instance_name = str(
        item.get("instance_name") or item.get("instance") or provider_name
    )
    value = str(item.get("value") or "").strip()
    if not value and provider_name and instance_name:
        value = f"{name}@{instance_name}@{provider_name}"
    tenant_model_id = (
        item.get("tenant_model_id")
        or item.get("tenant_llm_id")
        or item.get("tenant_id")
        or item.get("llm_id")
    )
    return {
        "id": model_id or name,
        "value": value or model_id or name,
        "model_type": model_types,
        "name": name,
        "provider_id": str(item.get("provider_id") or provider_name),
        "provider_name": provider_name,
        "instance_id": str(item.get("instance_id") or instance_name),
        "instance_name": instance_name,
        "tenant_model_id": (
            str(tenant_model_id) if tenant_model_id is not None else None
        ),
    }


def _iter_ragflow_tenant_model_candidates(payload: Any):
    if isinstance(payload, dict):
        data = payload.get("data") if "data" in payload else payload
        if data is not payload:
            yield from _iter_ragflow_tenant_model_candidates(data)
            return
        for factory_id, value in payload.items():
            if isinstance(value, dict) and isinstance(value.get("llm"), list):
                for item in value["llm"]:
                    if not isinstance(item, dict):
                        continue
                    model_name = item.get("name") or item.get("llm_name")
                    tenant_model_id = item.get("id")
                    if model_name and tenant_model_id is not None:
                        yield str(model_name), str(factory_id), str(tenant_model_id)
            yield from _iter_ragflow_tenant_model_candidates(value)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                model_name = (
                    item.get("llm_name") or item.get("name") or item.get("model_name")
                )
                factory_id = (
                    item.get("fid") or item.get("factory_id") or item.get("provider")
                )
                tenant_model_id = item.get("id") or item.get("tenant_model_id")
                if model_name and factory_id and tenant_model_id is not None:
                    yield str(model_name), str(factory_id), str(tenant_model_id)
            yield from _iter_ragflow_tenant_model_candidates(item)


async def _fetch_ragflow_tenant_model_lookup(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for path in ("/api/v1/users/me/models", "/v1/llm/list"):
        try:
            resp = await client.get(f"{base_url}{path}", headers=headers)
        except httpx.RequestError:
            continue
        if resp.status_code >= 400:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue
        for (
            model_name,
            factory_id,
            tenant_model_id,
        ) in _iter_ragflow_tenant_model_candidates(payload):
            lookup.setdefault((model_name, factory_id), tenant_model_id)
    return lookup


async def _list_ragflow_models(
    session: AsyncSession,
    tenant_id: str,
    model_type: str | None,
) -> list[dict[str, Any]]:
    row = await session.scalar(
        select(ExternalKnowledgeConfig).where(
            ExternalKnowledgeConfig.tenant_id == tenant_id
        )
    )
    if row is None or row.backend != "ragflow" or not row.base_url or not row.api_key:
        return []
    base_url = row.base_url.rstrip("/")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {row.api_key}"}
    params = {"type": model_type} if model_type else None
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.get(
            f"{base_url}/api/v1/models", params=params, headers=headers
        )
        tenant_model_lookup = await _fetch_ragflow_tenant_model_lookup(
            client,
            base_url,
            headers,
        )
    if resp.status_code >= 400:
        logger.warning(
            "RAGFlow model list failed: HTTP %s %s", resp.status_code, resp.text[:300]
        )
        return []
    payload = resp.json()
    raw_items: Any
    if isinstance(payload, dict):
        raw_items = payload.get("data")
        if isinstance(raw_items, dict):
            raw_items = (
                raw_items.get("items")
                or raw_items.get("models")
                or raw_items.get("data")
                or []
            )
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []
    models = [_normalize_ragflow_model(item) for item in raw_items]
    normalized_models = [m for m in models if m is not None]
    for model in normalized_models:
        if model.get("tenant_model_id"):
            continue
        model_name = str(model.get("name") or "")
        instance_name = str(model.get("instance_name") or "")
        provider_name = str(model.get("provider_name") or "")
        tenant_model_id = tenant_model_lookup.get(
            (model_name, instance_name)
        ) or tenant_model_lookup.get((model_name, provider_name))
        if tenant_model_id:
            model["tenant_model_id"] = tenant_model_id
    return normalized_models


async def _get_owned(
    session: AsyncSession, provider_id: UUID, tenant_id: str
) -> Provider:
    stmt = select(Provider).where(
        Provider.id == provider_id, Provider.tenant_id == tenant_id
    )
    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_id}' not found",
        )
    return obj


# ─── Routes ───────────────────────────────────────────────────────────────────


@models_router.get(
    "/models", response_model=ApiResponse, summary="List configured models"
)
async def list_models(
    type: str | None = Query(default=None),  # noqa: A002 - match RAGFlow query name
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    ragflow_models = await _list_ragflow_models(session, tenant_id, type)
    if ragflow_models:
        return ApiResponse(data=ragflow_models)

    stmt = (
        select(Provider)
        .where(Provider.tenant_id == tenant_id, Provider.enabled.is_(True))
        .order_by(Provider.created_at.desc())
    )
    result = await session.execute(stmt)
    providers = result.scalars().all()
    items: list[dict[str, Any]] = []
    for provider in providers:
        for model in provider.models or []:
            model_types = _infer_model_types(provider.name, model)
            if type and type not in model_types:
                continue
            items.append(
                {
                    "id": model,
                    "value": model,
                    "model_type": model_types,
                    "name": model,
                    "provider_id": str(provider.id),
                    "provider_name": provider.name,
                    "instance_id": str(provider.id),
                    "instance_name": provider.name,
                    "tenant_model_id": None,
                }
            )
    return ApiResponse(data=items)


@router.get("", response_model=ApiResponse, summary="List providers")
async def list_providers(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    stmt = (
        select(Provider)
        .where(Provider.tenant_id == tenant_id)
        .order_by(Provider.created_at.desc())
    )
    result = await session.execute(stmt)
    providers = result.scalars().all()
    items = [
        ProviderResponse.from_orm_provider(p).model_dump(mode="json") for p in providers
    ]
    return ApiResponse(data={"items": items, "total": len(items)})


@router.post(
    "",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a provider",
)
async def create_provider(
    body: ProviderCreate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    # Reject duplicate names within the same tenant. Cheap pre-check; the
    # DB still has the final say on uniqueness via a partial index.
    existing_stmt = select(Provider).where(
        Provider.tenant_id == tenant_id, Provider.name == body.name.strip()
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider with name '{body.name}' already exists",
        )

    provider = Provider(
        tenant_id=tenant_id,
        name=body.name.strip(),
        description=body.description.strip(),
        base_url=body.base_url,
        api_key=body.api_key,
        models=body.models,
        enabled=body.enabled,
    )
    session.add(provider)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Likely a tenant_id FK violation when the tenant row is missing.
        logger.exception("Failed to insert provider")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create provider: {exc.orig}",
        ) from exc
    await session.refresh(provider)
    return ApiResponse(
        data=ProviderResponse.from_orm_provider(provider).model_dump(mode="json")
    )


@router.post(
    "/fetch-models",
    response_model=ApiResponse,
    summary="Fetch the model list from a provider's configured models endpoint",
)
async def fetch_models(
    body: FetchModelsRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Proxy a GET against ``{base_url}/models`` without rewriting base_url.

    Browsers can't call third-party LLM endpoints directly (CORS), so the
    UI's "获取" button posts here and the manager performs the request
    server-side. Auth resolution order:

    1. ``body.api_key`` (caller-supplied, plaintext)
    2. ``body.provider_id``: load the stored key for that provider, but
       only if it belongs to the caller's tenant — otherwise treat it as
       not found to avoid leaking secrets across tenants.
    3. No key — many local providers (vLLM, Ollama) don't require one.
    """
    api_key = body.api_key.strip()

    if not api_key and body.provider_id is not None:
        provider = await _get_owned(session, body.provider_id, tenant_id)
        api_key = provider.api_key or ""

    # ``base_url`` is the API base selected by the user. Do not guess a
    # version prefix: tests and deployed NineClaw instances must use the same
    # configured value.
    upstream_url = _provider_endpoint(body.base_url, "models")

    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            res = await client.get(upstream_url, headers=headers)
    except httpx.RequestError as exc:
        # DNS, connection refused, timeout, TLS errors — all surface here.
        logger.warning("fetch-models network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"无法连接 {upstream_url}: {exc.__class__.__name__}",
        ) from exc

    if res.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效或权限不足",
        )
    if res.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"上游 404：{upstream_url}",
        )
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游返回 {res.status_code}: {res.text[:200]}",
        )

    try:
        payload = res.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游返回的不是 JSON",
        ) from exc

    # OpenAI-compatible shape: { object: "list", data: [{ id: str, ... }, ...] }
    # Some servers omit the ``object`` field, some return ``data`` directly
    # as a list of strings. Be tolerant.
    raw = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游响应缺少 data 数组",
        )

    seen: set[str] = set()
    models: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            mid = item.get("id") or item.get("model") or item.get("name")
        elif isinstance(item, str):
            mid = item
        else:
            mid = None
        if not isinstance(mid, str):
            continue
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        models.append(mid)

    models.sort()

    return ApiResponse(
        data=FetchModelsResponse(
            models=models,
            total=len(models),
            upstream_url=upstream_url,
        ).model_dump(mode="json")
    )


@router.post(
    "/chat/completions",
    summary="Proxy a chat completion request to a registered provider",
)
async def chat_completions(
    body: ProviderChatCompletionRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Proxy OpenAI-compatible chat completions through the manager.

    The browser only sends ``provider_id`` and ``model``. The manager resolves
    the provider's stored ``base_url`` and ``api_key`` server-side, so saved
    secrets are never exposed to the frontend. The response is normalized to
    SSE because the comparison UI renders each model incrementally.
    """
    provider = await _get_owned(session, body.provider_id, tenant_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider.name}' 已禁用",
        )
    if provider.models and body.model not in provider.models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 '{body.model}' 不属于 Provider '{provider.name}'",
        )

    upstream_url = _provider_endpoint(provider.base_url, "chat/completions")
    headers: dict[str, str] = {
        "Accept": "text/event-stream, application/json",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    payload: dict[str, object] = {
        "model": body.model,
        "messages": [m.model_dump(exclude_none=True) for m in body.messages],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    # DashScope Qwen3 thinking models otherwise stream only reasoning_content first,
    # which looks like a hang in the playground. Prefer direct answers for UX.
    if _is_dashscope_base(provider.base_url):
        model_l = (body.model or "").lower()
        if "qwen3" in model_l or model_l.startswith("qwq"):
            payload["enable_thinking"] = False

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        try:
            async with httpx.AsyncClient(
                timeout=None,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    upstream_url,
                    headers=headers,
                    json=payload,
                    timeout=httpx.Timeout(60.0, read=None),
                ) as res:
                    if res.status_code >= 400:
                        body_bytes = await res.aread()
                        detail = body_bytes.decode("utf-8", errors="replace")[:500]
                        yield {
                            "event": "error",
                            "data": json.dumps(
                                {
                                    "error": f"上游返回 {res.status_code}: {detail}",
                                },
                                ensure_ascii=False,
                            ),
                        }
                        return

                    content_type = res.headers.get("content-type", "")
                    if "text/event-stream" not in content_type:
                        data = await res.aread()
                        try:
                            payload_json = json.loads(data)
                        except ValueError:
                            yield {
                                "event": "error",
                                "data": json.dumps(
                                    {"error": "上游返回的不是 JSON 或 SSE"},
                                    ensure_ascii=False,
                                ),
                            }
                            return
                        yield {
                            "data": json.dumps(payload_json, ensure_ascii=False),
                        }
                        yield {"data": "[DONE]"}
                        return

                    async for line in res.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        yield {"data": data}
                        if data == "[DONE]":
                            return
        except httpx.RequestError as exc:
            logger.warning("chat completion network error: %s", exc)
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": f"无法连接 {upstream_url}: {exc.__class__.__name__}",
                    },
                    ensure_ascii=False,
                ),
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("chat completion unexpected error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_stream())


_ASR_MAX_BYTES = 25 * 1024 * 1024
# DashScope Qwen-ASR chat/completions base64 path has ~10MB encoded limit.
_DASHSCOPE_ASR_MAX_BYTES = 7 * 1024 * 1024
# GLM-ASR / Whisper 类接口通常只接受纯音频容器；.mp4 视频会被上游拒绝
_ASR_ALLOWED_SUFFIXES = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".webm",
    ".opus",
    ".wma",
}
_ASR_MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
}


def _is_qwen_asr_model(model: str) -> bool:
    """Qwen-ASR / Qwen-Audio ASR models use chat completions + input_audio."""
    name = (model or "").strip().lower()
    if not name:
        return False
    if "filetrans" in name:
        # Async file-transcription API — not supported by this playground proxy.
        return False
    return ("qwen" in name and "asr" in name) or "qwen-audio" in name


def _asr_audio_mime(filename: str, content_type: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("audio/"):
        return ct
    suffix = ""
    if "." in filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower()
    return _ASR_MIME_BY_SUFFIX.get(suffix, "application/octet-stream")


def _extract_transcription_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    raw_text = payload.get("text")
    if isinstance(raw_text, str):
        return raw_text
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("text")
        if isinstance(nested, str):
            return nested
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    return "".join(parts)
            delta = first.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                return delta["content"]
    return ""


async def _transcribe_dashscope_qwen_asr(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str | None,
    language: str | None,
) -> tuple[str, dict[str, Any]]:
    """DashScope Qwen3-ASR via OpenAI-compatible chat/completions + input_audio."""
    if len(audio_bytes) > _DASHSCOPE_ASR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "百炼 Qwen-ASR 音频过大（建议 ≤7MB）。"
                "请缩短录音或压缩后再试。"
            ),
        )

    upstream_url = _provider_endpoint(base_url, "chat/completions")
    mime = _asr_audio_mime(filename, content_type)
    data_uri = f"data:{mime};base64,{base64.b64encode(audio_bytes).decode('ascii')}"
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    asr_options: dict[str, Any] = {"enable_itn": False}
    if language and language.strip():
        asr_options["language"] = language.strip()

    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "asr_options": asr_options,
    }

    try:
        res = await client.post(upstream_url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        logger.warning("dashscope qwen-asr network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"无法连接 {upstream_url}: {exc.__class__.__name__}",
        ) from exc

    if res.status_code >= 400:
        detail = res.text[:500]
        lower = detail.lower()
        if "product is not activated" in lower or "not activated" in lower:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"上游返回 {res.status_code}: 百炼 Qwen-ASR 未开通，或 API Key 与"
                    "区域不匹配。请在控制台开通对应 ASR 模型，并确认 base_url 与 Key "
                    "同属北京站或国际站。原始信息："
                    f"{detail}"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游返回 {res.status_code}: {detail}",
        )

    try:
        body = res.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游返回的不是 JSON",
        ) from exc

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游 ASR 响应格式无效",
        )

    err_code = str(body.get("code") or "").strip()
    err_msg = str(body.get("message") or "").strip()
    if err_code and err_code.lower() not in {"", "success", "null"}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游 ASR 错误：{err_code}: {err_msg or str(body)[:300]}",
        )

    text = _extract_transcription_text(body)
    return text, body


@router.post(
    "/audio/transcriptions",
    response_model=ApiResponse,
    summary="Proxy speech-to-text (ASR) to a registered provider",
)
async def audio_transcriptions(
    provider_id: UUID = Form(...),
    model: str = Form(..., min_length=1, max_length=256),
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Proxy ASR for OpenAI-compatible providers and DashScope Qwen-ASR.

    - Paratera / Whisper-style: multipart ``/audio/transcriptions``
    - DashScope Qwen-ASR: ``/chat/completions`` + ``input_audio`` (base64)
    """
    provider = await _get_owned(session, provider_id, tenant_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider.name}' 已禁用",
        )
    dashscope = _is_dashscope_base(provider.base_url)
    qwen_asr = _is_qwen_asr_model(model)
    # 百炼 ASR：允许直接使用 qwen3-asr-flash，即使未写入 models 列表
    if provider.models and model not in provider.models:
        if not (dashscope and qwen_asr):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"模型 '{model}' 不属于 Provider '{provider.name}'",
            )

    filename = (file.filename or "audio.webm").strip() or "audio.webm"
    suffix = ""
    if "." in filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower()
    if suffix and suffix not in _ASR_ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"不支持的音频格式：{suffix}。"
                "请上传 wav / mp3 / m4a / aac / flac / ogg / webm 等音频文件"
                "（不要上传 mp4 视频）"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="音频文件为空",
        )
    if len(content) > _ASR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="音频过大，请上传 25MB 以内的文件",
        )

    base = provider.base_url.rstrip("/")
    content_type = file.content_type or "application/octet-stream"
    # dashscope / qwen_asr 已在上方校验 models 时计算过；此处保持一致
    dashscope = _is_dashscope_base(provider.base_url)
    qwen_asr = _is_qwen_asr_model(model)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            # DashScope does not expose Whisper-style /audio/transcriptions for
            # Qwen-ASR; calling it often ends in ReadError / connection reset.
            if dashscope and qwen_asr:
                text, payload = await _transcribe_dashscope_qwen_asr(
                    client,
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    model=model,
                    audio_bytes=content,
                    filename=filename,
                    content_type=content_type,
                    language=language,
                )
                return ApiResponse(data={"text": text, "raw": payload})

            if "filetrans" in model.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"模型 '{model}' 为异步文件转写（filetrans），"
                        "当前体验面板不支持。请改用 qwen3-asr-flash。"
                    ),
                )

            upstream_url = _provider_endpoint(base, "audio/transcriptions")
            headers: dict[str, str] = {
                "Accept": "application/json",
                "User-Agent": "nineclaw-manager/0.1",
            }
            if provider.api_key:
                headers["Authorization"] = f"Bearer {provider.api_key}"

            form_data: dict[str, str] = {"model": model}
            if language and language.strip():
                form_data["language"] = language.strip()

            try:
                res = await client.post(
                    upstream_url,
                    headers=headers,
                    data=form_data,
                    files={"file": (filename, content, content_type)},
                )
            except httpx.RequestError as exc:
                # Some DashScope ASR aliases still fail on /transcriptions —
                # fall back to Qwen chat ASR when the model name looks right.
                if dashscope and ("asr" in model.lower() or "audio" in model.lower()):
                    logger.info(
                        "transcriptions failed (%s), falling back to Qwen-ASR chat",
                        exc.__class__.__name__,
                    )
                    text, payload = await _transcribe_dashscope_qwen_asr(
                        client,
                        base_url=provider.base_url,
                        api_key=provider.api_key,
                        model=model,
                        audio_bytes=content,
                        filename=filename,
                        content_type=content_type,
                        language=language,
                    )
                    return ApiResponse(data={"text": text, "raw": payload})
                logger.warning("audio transcription network error: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"无法连接 {upstream_url}: {exc.__class__.__name__}",
                ) from exc

            if res.status_code >= 400:
                if dashscope and res.status_code in {404, 405} and (
                    "asr" in model.lower() or "audio" in model.lower()
                ):
                    text, payload = await _transcribe_dashscope_qwen_asr(
                        client,
                        base_url=provider.base_url,
                        api_key=provider.api_key,
                        model=model,
                        audio_bytes=content,
                        filename=filename,
                        content_type=content_type,
                        language=language,
                    )
                    return ApiResponse(data={"text": text, "raw": payload})
                detail = res.text[:500]
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"上游返回 {res.status_code}: {detail}",
                )

            try:
                payload = res.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="上游返回的不是 JSON",
                ) from exc

            text = _extract_transcription_text(payload)
            return ApiResponse(
                data={
                    "text": text,
                    "raw": payload if isinstance(payload, dict) else None,
                }
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.warning("audio transcription network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ASR 网络错误: {exc.__class__.__name__}",
        ) from exc


_TTS_ALLOWED_FORMATS = {"mp3", "wav", "opus", "aac", "flac", "pcm"}
_TTS_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "pcm": "audio/L16",
}
_DASHSCOPE_TTS_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def _is_dashscope_base(base_url: str) -> bool:
    lower = (base_url or "").lower()
    return "dashscope.aliyuncs.com" in lower or "dashscope-intl.aliyuncs.com" in lower


def _is_qwen_tts_model(model: str) -> bool:
    """Native DashScope multimodal TTS is only for Qwen-TTS family models."""
    name = (model or "").strip().lower().replace("_", "-")
    if not name:
        return False
    if "qwen3-tts" in name or "qwen-tts" in name:
        return True
    return "qwen" in name and "tts" in name


def _is_minimax_speech_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return "minimax" in name or "speech-0" in name or "speech-2" in name


def _dashscope_api_host(base_url: str) -> str:
    """Pick CN vs intl DashScope host from the provider base_url."""
    lower = (base_url or "").lower()
    if "dashscope-intl" in lower:
        return "https://dashscope-intl.aliyuncs.com"
    return "https://dashscope.aliyuncs.com"


def _dashscope_multimodal_tts_url(base_url: str) -> str:
    return f"{_dashscope_api_host(base_url)}{_DASHSCOPE_TTS_PATH}"


def _format_dashscope_tts_error(status_code: int, body: str) -> str:
    """Rewrite common DashScope TTS errors into actionable Chinese hints."""
    lower = (body or "").lower()
    if (
        "product is not activated" in lower
        or "not activated" in lower
        or "unpurchased" in lower
    ):
        return (
            f"上游返回 {status_code}: 百炼/DashScope 语音合成未开通，或 API Key 与"
            "区域不匹配。请确认：1) 控制台已开通 Model Studio / Qwen-TTS；"
            "2) Provider base_url 与 Key 同属北京站（dashscope.aliyuncs.com）或"
            "国际站（dashscope-intl.aliyuncs.com）。原始信息："
            f"{body[:280]}"
        )
    if "voice" in lower and ("invalid" in lower or "not support" in lower):
        return (
            f"上游返回 {status_code}: 音色无效或不被当前模型支持。"
            f"请换用该模型支持的 voice 名称。原始信息：{body[:280]}"
        )
    return f"上游返回 {status_code}: {body[:500]}"


def _audio_ext_and_media(fmt: str, content: bytes, hint: str | None = None) -> tuple[str, str]:
    """Pick download extension + media type from format / magic bytes."""
    if hint and "audio/" in hint.lower():
        media = hint.split(";")[0].strip()
        if "wav" in media:
            return "wav", media
        if "mpeg" in media or "mp3" in media:
            return "mp3", media
        if "opus" in media:
            return "opus", media
        if "aac" in media:
            return "aac", media
        if "flac" in media:
            return "flac", media
        return fmt, media
    if content[:4] == b"RIFF":
        return "wav", "audio/wav"
    if content[:3] == b"ID3" or content[:2] == b"\xff\xfb":
        return "mp3", "audio/mpeg"
    return fmt, _TTS_MEDIA_TYPES.get(fmt, "application/octet-stream")


async def _fetch_dashscope_tts_audio(
    client: httpx.AsyncClient,
    *,
    api_key: str | None,
    base_url: str,
    model: str,
    text: str,
    voice: str | None,
    response_format: str,
) -> tuple[bytes, str]:
    """DashScope Qwen-TTS: multimodal-generation with voice inside ``input``.

    Official shape (CN / intl)::

        POST {host}/api/v1/services/aigc/multimodal-generation/generation
        {"model": "...", "input": {"text": "...", "voice": "Cherry"}}
    """
    del response_format  # Qwen-TTS HTTP API returns wav URL; ignore OpenAI format
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    voice_name = (voice or "").strip() or "Cherry"
    payload: dict[str, Any] = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice_name,
        },
    }
    upstream = _dashscope_multimodal_tts_url(base_url)

    res = await client.post(upstream, headers=headers, json=payload)
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_format_dashscope_tts_error(res.status_code, res.text),
        )
    try:
        data = res.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="DashScope TTS 返回的不是 JSON",
        ) from exc

    # Some gateways return HTTP 200 with code/message error fields.
    if isinstance(data, dict):
        err_code = str(data.get("code") or "").strip()
        err_msg = str(data.get("message") or "").strip()
        if err_code and err_code.lower() not in {"", "success", "null"}:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_format_dashscope_tts_error(
                    int(data.get("status_code") or 400),
                    err_msg or json.dumps(data, ensure_ascii=False)[:500],
                ),
            )

    output = data.get("output") if isinstance(data, dict) else None
    audio = output.get("audio") if isinstance(output, dict) else None
    if not isinstance(audio, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"DashScope TTS 响应缺少 audio：{str(data)[:300]}",
        )

    b64 = audio.get("data")
    if isinstance(b64, str) and b64.strip():
        try:
            return base64.b64decode(b64), "audio/wav"
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="DashScope TTS base64 音频无法解码",
            ) from exc

    audio_url = audio.get("url")
    if isinstance(audio_url, str) and audio_url.strip():
        audio_res = await client.get(audio_url.strip())
        if audio_res.status_code >= 400 or not audio_res.content:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"拉取 DashScope 音频失败：HTTP {audio_res.status_code}",
            )
        ct = audio_res.headers.get("content-type")
        return audio_res.content, ct or "audio/wav"

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="DashScope TTS 未返回可用音频 data/url",
    )


def _unwrap_openai_tts_bytes(res: httpx.Response) -> bytes | None:
    content = res.content or b""
    if not content:
        return None
    content_type_header = (res.headers.get("content-type") or "").lower()
    if "application/json" not in content_type_header and content[:1] not in (b"{", b"["):
        return content
    try:
        wrapped = res.json()
    except ValueError:
        return content if content else None
    if not isinstance(wrapped, dict):
        return None
    audio_b64: Any = wrapped.get("audio")
    if audio_b64 is None:
        audio_b64 = wrapped.get("data")
    if audio_b64 is None and isinstance(wrapped.get("output"), dict):
        audio_b64 = wrapped["output"].get("audio")
    if isinstance(audio_b64, dict):
        # Prefer inline base64; URL handled by DashScope path
        nested_url = audio_b64.get("url")
        audio_b64 = audio_b64.get("data") or audio_b64.get("audio")
        if (not isinstance(audio_b64, str) or not audio_b64.strip()) and nested_url:
            return None
    if isinstance(audio_b64, str) and audio_b64.strip():
        try:
            return base64.b64decode(audio_b64)
        except Exception:
            return None
    return None


@router.post(
    "/audio/speech",
    summary="Proxy text-to-speech (TTS) to a registered provider",
    responses={
        200: {
            "content": {
                "audio/mpeg": {},
                "audio/wav": {},
                "audio/opus": {},
                "audio/aac": {},
                "audio/flac": {},
            },
            "description": "Synthesized audio bytes",
        }
    },
)
async def audio_speech(
    body: ProviderSpeechRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    """Proxy TTS like ASR: keep API keys server-side, return playable audio bytes.

    Tries OpenAI-compatible ``/audio/speech`` first; for DashScope (Qwen-TTS)
    falls back to multimodal-generation when the compatible route is unavailable.
    """
    provider = await _get_owned(session, body.provider_id, tenant_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider.name}' 已禁用",
        )
    if provider.models and body.model not in provider.models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 '{body.model}' 不属于 Provider '{provider.name}'",
        )

    fmt = (body.response_format or "mp3").strip().lower()
    if fmt not in _TTS_ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"不支持的音频格式：{fmt}。"
                f"可选：{', '.join(sorted(_TTS_ALLOWED_FORMATS))}"
            ),
        )

    text = body.input.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="合成文本不能为空",
        )

    voice = body.voice.strip() if body.voice and body.voice.strip() else None
    base = provider.base_url.rstrip("/")
    upstream_url = _provider_endpoint(base, "audio/speech")
    headers: dict[str, str] = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    payload: dict[str, Any] = {
        "model": body.model,
        "input": text,
        "response_format": fmt,
    }
    if voice:
        payload["voice"] = voice
    if body.speed is not None:
        payload["speed"] = body.speed

    dashscope_host = _is_dashscope_base(provider.base_url)
    qwen_tts = _is_qwen_tts_model(body.model)
    content: bytes | None = None
    media_hint: str | None = None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            # DashScope /compatible-mode/v1 不提供 OpenAI 的 /audio/speech（会稳定 404）。
            # Qwen-TTS 走原生 multimodal-generation；其它模型给出可操作提示。
            if dashscope_host:
                if qwen_tts:
                    content, media_hint = await _fetch_dashscope_tts_audio(
                        client,
                        api_key=provider.api_key,
                        base_url=provider.base_url,
                        model=body.model,
                        text=text,
                        voice=voice,
                        response_format=fmt,
                    )
                else:
                    hint = (
                        f"百炼兼容模式不支持 /audio/speech（模型 '{body.model}' 会 404）。"
                        "请在该 Provider 开启并选用 Qwen-TTS 模型，例如 "
                        "qwen3-tts-flash，音色使用 Cherry / Serena / Ethan。"
                    )
                    if _is_minimax_speech_model(body.model):
                        hint += (
                            " 当前选中的是 MiniMax/speech-*，不能走 Qwen-TTS 原生接口。"
                        )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=hint,
                    )
            else:
                try:
                    res = await client.post(upstream_url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    logger.warning("audio speech network error: %s", exc)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"无法连接 {upstream_url}: {exc.__class__.__name__}",
                    ) from exc

                if res.status_code < 400:
                    content = _unwrap_openai_tts_bytes(res)
                    media_hint = res.headers.get("content-type")
                else:
                    body_text = (res.text or "").strip()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            f"上游返回 {res.status_code}"
                            + (f": {body_text[:500]}" if body_text else f"（{upstream_url}）")
                        ),
                    )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.warning("audio speech network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TTS 网络错误: {exc.__class__.__name__}",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游返回空音频",
        )

    ext, media_type = _audio_ext_and_media(fmt, content, media_hint)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="speech.{ext}"',
            "Cache-Control": "no-store",
        },
    )


def _normalize_rerank_results(
    payload: object,
    documents: list[str],
    top_n: int | None,
) -> list[dict[str, object]]:
    """Normalize OpenAI / Jina / Cohere-style rerank responses."""
    rows: list[dict[str, object]] = []
    raw_results: list[object] = []
    if isinstance(payload, dict):
        maybe = payload.get("results")
        if isinstance(maybe, list):
            raw_results = maybe
        elif isinstance(payload.get("data"), list):
            raw_results = payload["data"]  # type: ignore[assignment]
        elif isinstance(payload.get("data"), dict):
            nested = payload["data"].get("results")  # type: ignore[union-attr]
            if isinstance(nested, list):
                raw_results = nested
    elif isinstance(payload, list):
        raw_results = payload

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            continue
        score_raw = (
            item.get("relevance_score")
            if item.get("relevance_score") is not None
            else item.get("score")
        )
        try:
            score = float(score_raw) if score_raw is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        text = ""
        doc_field = item.get("document")
        if isinstance(doc_field, dict) and isinstance(doc_field.get("text"), str):
            text = doc_field["text"]
        elif isinstance(doc_field, str):
            text = doc_field
        elif 0 <= index < len(documents):
            text = documents[index]
        rows.append(
            {
                "index": index,
                "relevance_score": score,
                "document": text,
            }
        )

    rows.sort(key=lambda row: float(row["relevance_score"]), reverse=True)
    if top_n is not None:
        rows = rows[:top_n]
    return rows


@router.post(
    "/embeddings",
    response_model=ApiResponse,
    summary="Proxy text embeddings to a registered provider",
)
async def provider_embeddings(
    body: ProviderEmbeddingRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Proxy OpenAI-compatible ``/embeddings`` for Embedding models.

    Used by the Embedding Playground to turn one or more texts into vectors
    without exposing the provider API key to the browser.
    """
    provider = await _get_owned(session, body.provider_id, tenant_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider.name}' 已禁用",
        )
    if provider.models and body.model not in provider.models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 '{body.model}' 不属于 Provider '{provider.name}'",
        )

    if isinstance(body.input, str):
        texts = [body.input.strip()] if body.input.strip() else []
    else:
        texts = [t.strip() for t in body.input if isinstance(t, str) and t.strip()]
    if not texts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="input 不能为空",
        )
    if len(texts) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="单次最多嵌入 64 条文本",
        )

    base = provider.base_url.rstrip("/")
    upstream_url = _provider_endpoint(base, "embeddings")
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    payload: dict[str, object] = {
        "model": body.model,
        "input": texts if len(texts) > 1 else texts[0],
    }
    encoding = (body.encoding_format or "float").strip() or "float"
    payload["encoding_format"] = encoding
    if body.dimensions is not None:
        payload["dimensions"] = body.dimensions

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            res = await client.post(upstream_url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        logger.warning("embeddings network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"无法连接 {upstream_url}: {exc.__class__.__name__}",
        ) from exc

    if res.status_code >= 400:
        detail = res.text[:500]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游返回 {res.status_code}: {detail}",
        )

    try:
        upstream_json = res.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游返回的不是 JSON",
        ) from exc

    # Normalize to OpenAI-style shape when possible; keep raw for playground JSON view.
    data_items = upstream_json.get("data") if isinstance(upstream_json, dict) else None
    if not isinstance(data_items, list):
        data_items = []

    embeddings: list[dict[str, object]] = []
    for i, item in enumerate(data_items):
        if not isinstance(item, dict):
            continue
        vec = item.get("embedding")
        if not isinstance(vec, list):
            continue
        idx = item.get("index") if isinstance(item.get("index"), int) else i
        embeddings.append(
            {
                "object": item.get("object") or "embedding",
                "index": idx,
                "embedding": vec,
                "dimensions": len(vec),
                "text": texts[idx] if 0 <= idx < len(texts) else None,
            }
        )

    if not embeddings and len(texts) == 1 and isinstance(upstream_json, dict):
        # Some gateways return a single vector at the top level.
        single = upstream_json.get("embedding")
        if isinstance(single, list):
            embeddings.append(
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": single,
                    "dimensions": len(single),
                    "text": texts[0],
                }
            )

    if not embeddings:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游未返回可用的 embedding 向量",
        )

    usage = upstream_json.get("usage") if isinstance(upstream_json, dict) else None
    model_out = (
        upstream_json.get("model")
        if isinstance(upstream_json, dict) and upstream_json.get("model")
        else body.model
    )

    return ApiResponse(
        data={
            "object": "list",
            "data": embeddings,
            "model": model_out,
            "usage": usage if isinstance(usage, dict) else None,
            "total": len(embeddings),
            "expected": len(texts),
            "inputs": texts,
            # Omit full upstream echo — keeps response size small for playground UI.
        }
    )


def _is_paratera_style_base(base_url: str) -> bool:
    """Paratera / AI智算云 llmapi gateways expose native rerank at /v1/p002/rerank."""
    lower = (base_url or "").lower()
    return (
        "paratera.com" in lower
        or "blsc.cn" in lower
        or "llmapi." in lower
    )


def _rerank_upstream_urls(base_url: str) -> list[str]:
    """Candidate rerank URLs, ordered by likelihood for the provider host.

    Paratera-style gateways route ``/v1/rerank`` through LiteLLM, which rejects
    custom providers (``Unsupported provider: custom``). Their working path is
    ``/v1/p002/rerank`` (智谱 GLM-Rerank). Other OpenAI/Jina-compatible hosts
    keep ``/v1/rerank`` as primary.
    """
    p002 = _provider_endpoint(base_url, "p002/rerank")
    standard = _provider_endpoint(base_url, "rerank")
    if _is_paratera_style_base(base_url):
        return [p002, standard]
    return [standard, p002]


def _is_litellm_rerank_unsupported(status_code: int, body: str) -> bool:
    if status_code < 400:
        return False
    lower = (body or "").lower()
    return "unsupported provider" in lower and (
        "custom" in lower or "rerank" in lower or "litellm" in lower
    )


@router.post(
    "/rerank",
    response_model=ApiResponse,
    summary="Proxy document rerank to a registered provider",
)
async def provider_rerank(
    body: ProviderRerankRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    """Proxy OpenAI / Jina-compatible ``/rerank`` for Rerank models.

    Typical flow on the WebUI: coarse-recall candidate chunks, then pass
    ``query + documents`` here to score and reorder by relevance.
    """
    provider = await _get_owned(session, body.provider_id, tenant_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider.name}' 已禁用",
        )
    if provider.models and body.model not in provider.models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 '{body.model}' 不属于 Provider '{provider.name}'",
        )

    documents = [doc.strip() for doc in body.documents if isinstance(doc, str) and doc.strip()]
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="documents 不能为空",
        )
    if len(documents) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="单次最多重排 100 条文档",
        )

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    payload: dict[str, object] = {
        "model": body.model,
        "query": body.query.strip(),
        "documents": documents,
    }
    if body.top_n is not None:
        payload["top_n"] = body.top_n
    # GLM-Rerank / 智谱默认返回 sigmoid 归一化分（相关文档容易全顶到 ~1.0）。
    # 请求原始 logit 分，排序不变，但分差更可读。
    if _is_paratera_style_base(provider.base_url) or "glm" in body.model.lower():
        payload["return_raw_scores"] = True

    candidate_urls = _rerank_upstream_urls(provider.base_url)
    last_error: str | None = None
    upstream_json: object | None = None
    used_url = candidate_urls[0]

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            for idx, upstream_url in enumerate(candidate_urls):
                used_url = upstream_url
                req_payload = dict(payload)
                # Only the native p002/Zhipu path honors return_raw_scores.
                if "return_raw_scores" in req_payload and "/p002/" not in upstream_url:
                    req_payload.pop("return_raw_scores", None)
                try:
                    res = await client.post(
                        upstream_url, headers=headers, json=req_payload
                    )
                except httpx.RequestError as exc:
                    logger.warning("rerank network error (%s): %s", upstream_url, exc)
                    last_error = (
                        f"无法连接 {upstream_url}: {exc.__class__.__name__}"
                    )
                    continue

                if res.status_code < 400:
                    try:
                        upstream_json = res.json()
                    except ValueError:
                        last_error = f"{upstream_url} 返回的不是 JSON"
                        continue
                    break

                detail = res.text[:500]
                # LiteLLM custom-provider failure → try next candidate (p002).
                if _is_litellm_rerank_unsupported(res.status_code, detail) and idx + 1 < len(
                    candidate_urls
                ):
                    logger.info(
                        "rerank %s unsupported via litellm; retrying %s",
                        upstream_url,
                        candidate_urls[idx + 1],
                    )
                    last_error = f"上游返回 {res.status_code}: {detail}"
                    continue

                # 404 on primary → try alternate path once.
                if res.status_code in {404, 405} and idx + 1 < len(candidate_urls):
                    last_error = f"上游返回 {res.status_code}: {detail}"
                    continue

                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"上游返回 {res.status_code}: {detail}",
                )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.warning("rerank network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=last_error
            or f"无法连接 {used_url}: {exc.__class__.__name__}",
        ) from exc

    if upstream_json is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=last_error or f"无法完成 rerank（已尝试: {', '.join(candidate_urls)}）",
        )

    results = _normalize_rerank_results(upstream_json, documents, body.top_n)
    # 若上游未返回可用 results，退化为按原序附 0 分（便于排查）
    if not results:
        limit = body.top_n or len(documents)
        results = [
            {"index": i, "relevance_score": 0.0, "document": doc}
            for i, doc in enumerate(documents[:limit])
        ]

    usage = upstream_json.get("usage") if isinstance(upstream_json, dict) else None

    return ApiResponse(
        data={
            "results": results,
            "model": body.model,
            "total": len(results),
            "usage": usage if isinstance(usage, dict) else None,
        }
    )


@router.post(
    "/deploy",
    summary="Stream deployment of selected providers to selected NineClaw instances",
)
async def deploy_providers(
    body: DeployRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Push the selected providers + main model to each target nineclaw,
    streaming progress via Server-Sent Events.

    Sequential per instance — the user-facing wizard renders each event as
    "deploying" → "deployed"/"failed" so they should arrive one-by-one
    instead of all at once. On failure of a single instance we emit a
    ``failed`` event and continue with the next.

    Event payload (per instance)::

        { "instance_id": str,
          "name": str,
          "status": "pending" | "deploying" | "deployed" | "failed",
          "error": str | null }

    A final ``done`` event terminates the stream.
    """
    # Validate ownership and gather data up front; once the SSE stream
    # starts we can't return HTTP errors anymore.
    async with async_session_maker() as session:
        prov_stmt = select(Provider).where(
            Provider.tenant_id == tenant_id,
            Provider.id.in_(body.provider_ids),
        )
        providers = list((await session.execute(prov_stmt)).scalars().all())
        if len(providers) != len(set(body.provider_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分 provider 不存在或不属于当前租户",
            )

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

    # Preserve the order the user picked, not the DB order.
    by_id = {p.id: p for p in providers}
    ordered_providers = [by_id[pid] for pid in body.provider_ids if pid in by_id]
    inst_by_id = {i.id: i for i in instances}
    ordered_instances = [
        inst_by_id[iid] for iid in body.instance_ids if iid in inst_by_id
    ]

    # Build the new custom_providers payload exactly once — every instance
    # receives the same list. One entry per provider; models is a dict
    # keyed by model id (hermes format).
    # name_index maps (provider_name, model) -> {"provider_name": str, "model": str, ...}
    # so main_block and aux resolution can look up the right entry.
    new_custom_providers, name_index = _build_deploy_custom_providers(ordered_providers)

    main_block: dict[str, Any] | None = None
    if body.main_model is not None:
        key = (body.main_model.provider, body.main_model.model)
        target = name_index.get(key)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"主模型 {body.main_model.provider}/{body.main_model.model} "
                    "未在选中的 provider 中"
                ),
            )
        main_block = {
            "default": target["model"],
            "provider": target["provider_name"],
            "base_url": target["base_url"],
            "api_key": target["api_key"],
        }

    # Resolve every auxiliary entry against the same name_index so we
    # never push an aux assignment that references a custom_provider
    # we aren't writing. provider="auto" is a special sentinel meaning
    # "reset to follow main" — it bypasses name_index validation and is
    # passed through to hermes as-is.
    resolved_aux: list[tuple[str, str, str]] = []  # (task, provider_name, model)
    seen_tasks: set[str] = set()
    for aux in body.auxiliary_models:
        if aux.task in seen_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"辅助任务 {aux.task} 重复",
            )
        seen_tasks.add(aux.task)
        if aux.provider == "auto":
            resolved_aux.append((aux.task, "auto", ""))
            continue
        target = name_index.get((aux.provider, aux.model))
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"辅助任务 {aux.task} 引用的 {aux.provider}/{aux.model} "
                    "未在选中的 provider 中"
                ),
            )
        resolved_aux.append((aux.task, target["provider_name"], target["model"]))

    api_key = settings.nineclaw_token

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        # Snapshot frame of every instance before we start; the UI uses
        # this to render the initial "pending" list.
        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "pending",
                        "error": None,
                    }
                ),
            }

        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "deploying",
                        "error": None,
                    }
                ),
            }

            base_url = build_dashboard_base_url(inst.id)
            try:
                async with async_session_maker() as deployment_session:
                    locked_instance = await lock_instance_for_snapshot(
                        deployment_session,
                        tenant_id=tenant_id,
                        instance_id=inst.id,
                    )
                    actual = (locked_instance.actual_state or "").lower()
                    if actual != "running":
                        # Release the row lock before yielding to a potentially
                        # slow or disconnected SSE consumer.
                        await deployment_session.rollback()
                        yield {
                            "event": "status",
                            "data": json.dumps(
                                {
                                    "instance_id": inst.id,
                                    "name": inst.name,
                                    "status": "failed",
                                    "error": f"实例当前状态为 {actual or 'unknown'}，必须运行中才能部署",
                                }
                            ),
                        }
                        continue

                    async with HermesService(base_url=base_url, api_key=api_key) as svc:
                        current = await svc.get_config()
                        if not isinstance(current, dict):
                            current = {}
                        new_config = dict(current)
                        new_config["custom_providers"] = new_custom_providers
                        if main_block is not None:
                            new_config["model"] = main_block
                        new_config, _ = adapt_moa_config_to_instance(new_config)
                        provider_snapshot_entries = (
                            extract_provider_snapshot_from_hermes_config(new_config)
                        )
                        await svc.put_config(new_config)

                        snapshot_update: dict[str, Any] = {
                            "providers": provider_snapshot_entries,
                        }
                        if main_block is not None:
                            snapshot_update["model"] = {
                                "provider": main_block["provider"],
                                "model": main_block["default"],
                            }
                        try:
                            await persist_manager_resource_snapshot(
                                deployment_session,
                                tenant_id=tenant_id,
                                instance_id=inst.id,
                                **snapshot_update,
                            )
                            await deployment_session.commit()
                        except Exception as exc:
                            raise _SnapshotPersistError from exc

                        supported_aux_tasks = _extract_supported_auxiliary_tasks(
                            await svc.get_auxiliary_models()
                        )
                        # Push every customized auxiliary task. Tasks the user
                        # left at "follow main" are absent from resolved_aux,
                        # so hermes' existing assignment is left in place. Task
                        # names are Runtime-version-specific, so skip tasks the
                        # target instance does not advertise via /model/auxiliary.
                        for task, prov, mdl in resolved_aux:
                            if task not in supported_aux_tasks:
                                logger.warning(
                                    "deploy: skipping unsupported auxiliary task %s for %s",
                                    task,
                                    inst.id,
                                )
                                continue
                            await svc.set_model_assignment(
                                scope="auxiliary",
                                provider=prov,
                                model=mdl,
                                task=task,
                            )
            except HermesError as exc:
                logger.warning("deploy: hermes error for %s: %s", inst.id, exc.detail)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": f"Hermes {exc.status_code}: 配置部署失败",
                        }
                    ),
                }
                continue
            except _SnapshotPersistError:
                logger.exception("deploy: snapshot persistence failed for %s", inst.id)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": "部署状态保存失败，请稍后重试",
                        }
                    ),
                }
                continue
            except (httpx.RequestError, *asyncio_timeout_or_runtime()) as exc:
                logger.warning("deploy: connection error for %s: %s", inst.id, exc)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": f"无法连接实例: {exc.__class__.__name__}",
                        }
                    ),
                }
                continue
            except Exception as exc:  # pragma: no cover — defensive
                logger.exception("deploy: unexpected error for %s", inst.id)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "error": "部署失败，请稍后重试",
                        }
                    ),
                }
                continue

            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "deployed",
                        "error": None,
                    }
                ),
            }

        yield {"event": "done", "data": json.dumps({"finished": True})}

    return EventSourceResponse(event_stream())


def asyncio_timeout_or_runtime() -> tuple[type[BaseException], ...]:
    """Tuple of exceptions we treat as transient connection errors."""
    import asyncio

    return (asyncio.TimeoutError, RuntimeError)


# ─── Health check ────────────────────────────────────────────────────────────


_HEALTH_TIMEOUT_SECONDS = 5.0
_HEALTH_CONCURRENCY = 10


_RESPONSE_TEXT_MAX = 500


async def _probe_provider_health(base_url: str, api_key: str = "") -> tuple[str, str]:
    """Best-effort health classification for a single provider.

    Returns ``(status, response_text)`` where ``response_text`` is a short,
    human-readable snippet useful for debugging — the body of the upstream
    HTTP response, or the formatted exception class + message when the
    request never completed. ``response_text`` is bounded to
    ``_RESPONSE_TEXT_MAX`` characters and is never persisted; we only ship
    it back to the caller through the SSE stream.

    Mapping is intentionally simple per product spec:
      - HTTP 200/401/403 → ``online`` (server is reachable; auth failure
        still proves the model endpoint is alive)
      - any other status code → ``abnormal``
      - read/connect timeout (``_HEALTH_TIMEOUT_SECONDS``) → ``offline``
      - DNS / TCP / TLS / unexpected error → ``offline``

    Probes the configured OpenAI-compatible ``models`` endpoint rather than a
    generic health endpoint so the check verifies the same surface the
    model UI and deployments depend on. The configured base URL is used
    verbatim; no API version prefix is inferred.
    """
    url = _provider_endpoint(base_url, "models")
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "nineclaw-manager/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(
            timeout=_HEALTH_TIMEOUT_SECONDS,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = await client.get(url, headers=headers)
        body = (resp.text or "")[:_RESPONSE_TEXT_MAX]
        snippet = f"HTTP {resp.status_code} {url}\n{body}"
        # Product semantics: this check answers "is the upstream model
        # server alive?", not "are our credentials valid?". A 401/403 from
        # /v1/models still proves the target server and route are reachable,
        # so keep it online instead of "fixing" it to abnormal later.
        return (
            "online" if resp.status_code in (200, 401, 403) else "abnormal",
            snippet,
        )
    except (
        httpx.TimeoutException,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.PoolTimeout,
    ) as exc:
        return (
            "offline",
            f"timeout {_HEALTH_TIMEOUT_SECONDS:g}s {url} ({exc.__class__.__name__})",
        )
    except Exception as exc:  # noqa: BLE001 — explicit catch-all
        logger.debug("health probe error for %s: %s", url, exc)
        return ("offline", f"{exc.__class__.__name__}: {exc}"[:_RESPONSE_TEXT_MAX])


@router.get(
    "/health_check",
    summary="Stream concurrent health probes for the tenant's providers",
)
async def health_check_stream(
    tenant_id: str = Depends(get_tenant_id),
):
    """Run an HTTP-GET ``/v1/models`` probe against every provider's ``base_url``
    and stream the result as SSE.

    Probes run concurrently (bounded by ``_HEALTH_CONCURRENCY``) so a slow
    provider can't hold up the rest. Each completion immediately streams
    a ``status`` event, then we batch a single DB UPDATE per provider at
    the end so subsequent ``GET /providers`` already shows fresh values.

    Event shape::

        { "provider_id": str, "status": "online"|"abnormal"|"offline",
          "checked_at": ISO8601 }

    A final ``done`` event terminates the stream.
    """

    # Snapshot the rows up front. We don't keep the DB session open for the
    # full streaming duration since the probes can take seconds.
    async with async_session_maker() as session:
        stmt = select(Provider).where(Provider.tenant_id == tenant_id)
        rows = list((await session.execute(stmt)).scalars().all())

    # Detach from the session — we only need (id, base_url, api_key) downstream.
    targets: list[tuple[UUID, str, str]] = [
        (p.id, p.base_url, p.api_key or "") for p in rows
    ]

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        if not targets:
            yield {"event": "done", "data": json.dumps({"checked": 0})}
            return

        sem = asyncio.Semaphore(_HEALTH_CONCURRENCY)
        # Queue items: (provider_id, status, response_text, checked_at).
        queue: asyncio.Queue[tuple[UUID, str, str, str]] = asyncio.Queue()
        # Sentinel to mark task pool drained.
        _DONE = object()

        async def check_one(pid: UUID, url: str, api_key: str) -> None:
            async with sem:
                status_str, response_text = await _probe_provider_health(url, api_key)
            checked_at = _utcnow().isoformat()
            await queue.put((pid, status_str, response_text, checked_at))

        # Spawn all probes; coordinator finishes when all done.
        async def coordinator() -> None:
            await asyncio.gather(
                *(check_one(pid, url, api_key) for pid, url, api_key in targets),
                return_exceptions=True,
            )
            await queue.put(_DONE)  # type: ignore[arg-type]

        coord_task = asyncio.create_task(coordinator())

        # Drain results as they complete and forward as SSE events.
        results: list[tuple[UUID, str, str]] = []
        try:
            while True:
                item = await queue.get()
                if item is _DONE:  # type: ignore[comparison-overlap]
                    break
                pid, status_str, response_text, checked_at = item
                # Persistent record drops response_text — it's debug-only.
                results.append((pid, status_str, checked_at))
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "provider_id": str(pid),
                            "status": status_str,
                            "checked_at": checked_at,
                            "response_text": response_text,
                        }
                    ),
                }
        finally:
            await coord_task

        # Persist all results in a single transaction.
        if results:
            try:
                async with async_session_maker() as session:
                    for pid, status_str, checked_at in results:
                        await session.execute(
                            Provider.__table__.update()
                            .where(Provider.id == pid)
                            .values(
                                last_health_status=status_str,
                                last_checked_at=_utcnow(),
                            )
                        )
                    await session.commit()
            except Exception:
                logger.exception("Failed to persist health-check results")

        yield {"event": "done", "data": json.dumps({"checked": len(results)})}

    return EventSourceResponse(event_stream())


@router.get("/{provider_id}", response_model=ApiResponse, summary="Get a provider")
async def get_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    provider = await _get_owned(session, provider_id, tenant_id)
    return ApiResponse(
        data=ProviderResponse.from_orm_provider(provider).model_dump(mode="json")
    )


@router.put("/{provider_id}", response_model=ApiResponse, summary="Update a provider")
async def update_provider(
    provider_id: UUID,
    body: ProviderUpdate,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    provider = await _get_owned(session, provider_id, tenant_id)

    # If the caller is renaming, ensure the target name is unique among the
    # tenant's providers.
    if body.name is not None and body.name.strip() != provider.name:
        new_name = body.name.strip()
        clash_stmt = select(Provider).where(
            Provider.tenant_id == tenant_id,
            Provider.name == new_name,
            Provider.id != provider.id,
        )
        if (await session.execute(clash_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Provider with name '{new_name}' already exists",
            )
        provider.name = new_name

    if body.description is not None:
        provider.description = body.description.strip()
    if body.base_url is not None:
        provider.base_url = body.base_url
    # Special handling: ``None`` means "leave unchanged"; "" means "clear".
    if body.api_key is not None:
        provider.api_key = body.api_key
    if body.models is not None:
        provider.models = body.models
    if body.enabled is not None:
        provider.enabled = body.enabled
    provider.updated_at = _utcnow()

    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return ApiResponse(
        data=ProviderResponse.from_orm_provider(provider).model_dump(mode="json")
    )


@router.delete(
    "/{provider_id}", response_model=ApiResponse, summary="Delete a provider"
)
async def delete_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
) -> ApiResponse:
    provider = await _get_owned(session, provider_id, tenant_id)
    await session.delete(provider)
    await session.commit()
    return ApiResponse(data={"deleted": str(provider_id)})

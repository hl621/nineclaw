"""Source card management – list, create, get, update, delete."""

from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.source_loader import (
    DEFAULT_EXTRACTOR_CODE,
    WEB_SOURCES_DIR,
    ensure_default_extractor,
    get_all_sources,
    get_source,
)

router = APIRouter(prefix="/sources", tags=["sources"])


class CreateSourceRequest(BaseModel):
    source_id: str
    name: str
    description: str | None = None
    tags: list[str] = []
    weight: float = Field(default=0.5, ge=0, le=1)
    # Optional initial HTTP request template (stored under config.request)
    request: dict | None = None
    url_base: str | None = None


class UpdateSourceRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    weight: float | None = None
    url_base: str | None = None


@router.get("")
async def list_sources():
    sources = get_all_sources()
    return [
        {
            "source_id": s.source_id,
            "name": s.name,
            "description": s.description,
            "enabled": s.enabled,
            "tags": s.tags,
            "weight": s.weight,
            "has_proxy": bool(
                s.request_config.get("proxy_pool")
                or (s.request_config.get("use_proxy") and s.request_config.get("proxy_url"))
            ),
        }
        for s in sources
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(body: CreateSourceRequest):
    """Create a new source card (directory + config.json + default extract.py)."""
    source_id = body.source_id.strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    source_dir = WEB_SOURCES_DIR / source_id
    if source_dir.exists():
        # Heal incomplete cards (config without extract.py) so they show in list
        # instead of permanently blocking recreate with an opaque 409.
        if source_dir.is_dir() and (source_dir / "config.json").exists():
            ensure_default_extractor(source_dir)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Source already exists: {source_id}。"
                "该信源 ID 已被占用。请打开列表中的同名信源继续配置，"
                "或先删除后再新建；也可换用其他 ID（如 baidu_web）。"
            ),
        )

    source_dir.mkdir(parents=True, exist_ok=False)
    config: dict = {
        "name": body.name,
        "description": body.description,
        "enabled": True,
        "tags": body.tags,
        "weight": body.weight,
    }
    if body.url_base:
        config["url_base"] = body.url_base
    if body.request:
        config["request"] = body.request
    (source_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (source_dir / "extract.py").write_text(DEFAULT_EXTRACTOR_CODE, encoding="utf-8")
    return {
        "source_id": source_id,
        "name": body.name,
        "description": body.description,
        "tags": body.tags,
        "weight": body.weight,
    }


@router.get("/{source_id}")
async def get_source_detail(source_id: str):
    s = get_source(source_id)
    if not s:
        raise HTTPException(status_code=404, detail="Source not found")
    return {
        "source_id": s.source_id,
        "name": s.name,
        "description": s.description,
        "enabled": s.enabled,
        "tags": s.tags,
        "weight": s.weight,
        "request_config": s.request_config,
        "response_info": s.response_info,
        "url_base": s.url_base,
        "extractor_code": s.extractor_code_safe,
    }


@router.put("/{source_id}")
async def update_source(source_id: str, body: UpdateSourceRequest):
    """Update source card metadata."""
    source_dir = WEB_SOURCES_DIR / source_id
    config_path = source_dir / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key, value in body.model_dump(exclude_unset=True).items():
        config[key] = value
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    ensure_default_extractor(source_dir)

    return {
        "source_id": source_id,
        **{k: config.get(k) for k in ["name", "description", "enabled", "tags", "weight", "url_base"]},
    }


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str):
    """Delete an entire source card directory."""
    source_dir = WEB_SOURCES_DIR / source_id
    if not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="Source not found")
    shutil.rmtree(source_dir)

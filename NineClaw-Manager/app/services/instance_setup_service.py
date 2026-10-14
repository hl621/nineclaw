"""Initial guided setup for freshly created NineClaw instances."""

from __future__ import annotations

import io
import json
import logging
import shlex
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.services.docker_service import DockerService

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.external_knowledge_config import ExternalKnowledgeConfig
from app.models.mcp_server import McpServer
from app.models.provider import Provider
from app.services.docker_client import create_configured_docker_client
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.instance_agent_snapshot import (
    extract_provider_snapshot_from_hermes_config,
    persist_manager_resource_snapshot,
)
from app.services.knowledge_deploy_service import (
    ENV_QYRAG_DATASETS,
    build_rag_deploy_env,
    ensure_ragflow_plugin_enabled,
    resolve_ragflow_credentials,
    rewrite_hermes_dotenv_var_utf8,
)
from app.services.knowledge_factory import _get_knowledge_service
from app.services.moa_adapt_service import adapt_moa_config_to_instance
from app.services.nineclaw_bootstrap import build_dashboard_base_url
from app.services.skill_service import SkillError, SkillService
from app.services.websearch_deploy_service import (
    WEBSEARCH_PLUGIN_ID,
    build_websearch_deploy_env,
    merge_websearch_config,
)

logger = logging.getLogger(__name__)

# 创建实例时选中的技能统一落到 Hermes 原生扫描根 /opt/data/skills，
# 不带分类（/opt/data/skills/{slug}/），直接出现在实例技能列表的“未分类”。
# 旧的 /opt/nineclaw/external_skill + skills.external_dirs 方案在当前实例
# 镜像里不会被扫描（拷贝"成功"但列表不显示），已弃用。
NATIVE_SKILLS_ROOT = "/opt/data/skills"


def has_initial_setup(setup: Any) -> bool:
    if setup is None:
        return False
    return bool(
        getattr(setup, "provider_ids", None)
        or getattr(setup, "main_model", None)
        or getattr(setup, "auxiliary_models", None)
        or getattr(setup, "skill_slugs", None)
        or getattr(setup, "mcp_ids", None)
        or getattr(setup, "knowledge_ids", None)
        or getattr(setup, "web_source_ids", None)
    )


def summarize_initial_setup(setup: Any) -> dict[str, Any] | None:
    """Return a safe, serializable summary for DB/API visibility."""
    if not has_initial_setup(setup):
        return None

    main_model = getattr(setup, "main_model", None)
    return {
        "provider_count": len(getattr(setup, "provider_ids", None) or []),
        "main_model": (
            {
                "provider": getattr(main_model, "provider", ""),
                "model": getattr(main_model, "model", ""),
            }
            if main_model is not None
            else None
        ),
        "auxiliary_model_count": len(getattr(setup, "auxiliary_models", None) or []),
        "skill_count": len(getattr(setup, "skill_slugs", None) or []),
        "mcp_count": len(getattr(setup, "mcp_ids", None) or []),
        "knowledge_count": len(getattr(setup, "knowledge_ids", None) or []),
        "web_source_count": len(getattr(setup, "web_source_ids", None) or []),
    }


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


async def apply_initial_setup(
    *,
    instance_id: str,
    tenant_id: str,
    setup: Any,
    session: AsyncSession,
    docker_service: DockerService | None = None,
    container_id: str | None = None,
) -> bool:
    """Apply optional guided setup to a running fresh instance.

    Returns True when the caller should restart the container once after all
    writes complete.
    """
    if not has_initial_setup(setup):
        return False
    logger.info(
        "Applying initial setup for instance %s: %s",
        instance_id,
        summarize_initial_setup(setup),
    )

    config_patch: dict[str, Any] = {}
    env_patch: dict[str, str] = {}
    mcp_snapshot_entries: list[dict[str, Any]] = []
    knowledge_snapshot_entries: list[dict[str, str]] = []

    if getattr(setup, "provider_ids", None) or getattr(setup, "main_model", None):
        model_config, main_model_assignment, aux_models = await _build_model_setup(
            session, tenant_id, setup
        )
        config_patch.update(model_config)
        logger.info(
            "initial setup model patch prepared: instance=%s provider_count=%d aux_count=%d main_model=%s",
            instance_id,
            len(model_config.get("custom_providers", []) or []),
            len(aux_models),
            bool(model_config.get("model")),
        )
    else:
        main_model_assignment = None
        aux_models = []

    skill_slugs = list(getattr(setup, "skill_slugs", None) or [])
    if skill_slugs:
        _merge_skill_config(config_patch)
        logger.info(
            "initial setup skills selected: instance=%s skills=%s",
            instance_id,
            skill_slugs,
        )

    mcp_ids = list(getattr(setup, "mcp_ids", None) or [])
    if mcp_ids:
        mcp_entries, mcp_snapshot_entries = await _build_mcp_entries(
            session,
            tenant_id,
            mcp_ids,
            getattr(setup, "mcp_tools_config", None),
        )
        config_patch["mcp_servers"] = {
            **config_patch.get("mcp_servers", {}),
            **mcp_entries,
        }
        logger.info(
            "initial setup mcp patch prepared: instance=%s mcp_count=%d names=%s",
            instance_id,
            len(mcp_ids),
            sorted(config_patch["mcp_servers"].keys()),
        )

    knowledge_ids = list(getattr(setup, "knowledge_ids", None) or [])
    if knowledge_ids:
        (
            knowledge_config,
            knowledge_env,
            knowledge_snapshot_entries,
        ) = await _build_knowledge_setup(session, tenant_id, knowledge_ids)
        config_patch.update(knowledge_config)
        env_patch.update(knowledge_env)
        logger.info(
            "initial setup knowledge patch prepared: instance=%s knowledge_ids=%s env_keys=%s",
            instance_id,
            knowledge_ids,
            sorted(knowledge_env.keys()),
        )

    web_source_ids = [
        s.strip()
        for s in list(getattr(setup, "web_source_ids", None) or [])
        if s.strip()
    ]
    if web_source_ids:
        updated_web = merge_websearch_config(config_patch)
        config_patch.clear()
        config_patch.update(updated_web)
        env_patch.update(build_websearch_deploy_env(web_source_ids))
        logger.info(
            "initial setup websearch patch prepared: instance=%s source_ids=%s",
            instance_id,
            web_source_ids,
        )

    base_url = build_dashboard_base_url(instance_id)
    async with HermesService(base_url=base_url, api_key=settings.nineclaw_token) as svc:
        logger.info(
            "initial setup fetch current config: instance=%s dashboard_url=%s",
            instance_id,
            base_url,
        )
        current = await svc.get_config()
        if not isinstance(current, dict):
            current = {}
        merged_config = _deep_merge_dicts(current, config_patch)
        merged_config, moa_adapted = adapt_moa_config_to_instance(merged_config)
        if moa_adapted:
            logger.info(
                "initial setup adapted moa presets to deployed custom_providers: instance=%s",
                instance_id,
            )
        if config_patch or moa_adapted:
            logger.info(
                "initial setup put config: instance=%s patch_keys=%s",
                instance_id,
                sorted(config_patch.keys()),
            )
            await svc.put_config(merged_config)
            await persist_manager_resource_snapshot(
                session,
                tenant_id=tenant_id,
                instance_id=instance_id,
                providers=extract_provider_snapshot_from_hermes_config(merged_config),
            )
        # Each resource is recorded after its own remote write succeeds.  If a
        # later initial-setup stage fails, the caller still commits these facts.
        if mcp_snapshot_entries:
            await persist_manager_resource_snapshot(
                session,
                tenant_id=tenant_id,
                instance_id=instance_id,
                mcps=mcp_snapshot_entries,
            )
        for key, value in env_patch.items():
            logger.info("initial setup put env: instance=%s key=%s", instance_id, key)
            # Hermes PUT /api/env strips non-ASCII → empty JSON keys.
            # Put an ASCII-safe form first so .env never stays as {"": id}.
            put_value = value
            if key == ENV_QYRAG_DATASETS:
                try:
                    put_value = json.dumps(json.loads(value), ensure_ascii=True)
                except (TypeError, ValueError):
                    put_value = value
            await svc.put_env(key, put_value)

        # Rewrite QYRAG_DATASETS as UTF-8 Chinese via Docker exec so
        # `cat /opt/data/.env` shows {"策略分析": "..."} instead of \uXXXX.
        datasets_value = env_patch.get(ENV_QYRAG_DATASETS)
        if (
            datasets_value
            and docker_service is not None
            and (container_id or "").strip()
        ):
            try:
                await rewrite_hermes_dotenv_var_utf8(
                    docker_service,
                    container_id.strip(),
                    ENV_QYRAG_DATASETS,
                    datasets_value,
                )
            except Exception as rewrite_exc:
                logger.warning(
                    "initial setup: utf-8 dotenv rewrite failed for %s: %s "
                    "(ASCII-safe QYRAG_DATASETS already written via Hermes)",
                    instance_id,
                    rewrite_exc,
                )
        if main_model_assignment is not None:
            provider, model = main_model_assignment
            logger.info(
                "initial setup set main model: instance=%s provider=%s model=%s",
                instance_id,
                provider,
                model,
            )
            await svc.set_model_assignment(
                scope="main",
                provider=provider,
                model=model,
            )
            await persist_manager_resource_snapshot(
                session,
                tenant_id=tenant_id,
                instance_id=instance_id,
                model={"provider": provider, "model": model},
            )
        supported_aux_tasks: set[str] | None = None
        for task, provider, model in aux_models:
            if supported_aux_tasks is None:
                supported_aux_tasks = _extract_supported_auxiliary_tasks(
                    await svc.get_auxiliary_models()
                )
                logger.info(
                    "initial setup auxiliary supported tasks: instance=%s tasks=%s",
                    instance_id,
                    sorted(supported_aux_tasks),
                )
            if task not in supported_aux_tasks:
                logger.warning(
                    "initial setup: skipping unsupported auxiliary task %s for %s",
                    task,
                    instance_id,
                )
                continue
            logger.info(
                "initial setup set auxiliary model: instance=%s task=%s provider=%s model=%s",
                instance_id,
                task,
                provider,
                model,
            )
            await svc.set_model_assignment(
                scope="auxiliary",
                provider=provider,
                model=model,
                task=task,
            )
        if knowledge_ids:
            logger.info("initial setup enable ragflow plugin: instance=%s", instance_id)
            try:
                await ensure_ragflow_plugin_enabled(svc)
            except HermesError as exc:
                logger.warning(
                    "initial setup ragflow plugin enable skipped: instance=%s status=%s detail=%s",
                    instance_id,
                    exc.status_code,
                    exc.detail,
                )
            await persist_manager_resource_snapshot(
                session,
                tenant_id=tenant_id,
                instance_id=instance_id,
                knowledge_bases=knowledge_snapshot_entries,
            )
        if web_source_ids:
            logger.info(
                "initial setup enable websearch plugin: instance=%s plugin=%s",
                instance_id,
                WEBSEARCH_PLUGIN_ID,
            )
            try:
                await svc.enable_agent_plugin(WEBSEARCH_PLUGIN_ID)
            except HermesError as exc:
                logger.warning(
                    "initial setup websearch plugin enable skipped: instance=%s plugin=%s status=%s detail=%s",
                    instance_id,
                    WEBSEARCH_PLUGIN_ID,
                    exc.status_code,
                    exc.detail,
                )

    if skill_slugs:
        logger.info(
            "initial setup copy skills: instance=%s skills=%s", instance_id, skill_slugs
        )
        skill_snapshot_entries = await _copy_skills_to_container(
            instance_id,
            tenant_id,
            skill_slugs,
        )
        await persist_manager_resource_snapshot(
            session,
            tenant_id=tenant_id,
            instance_id=instance_id,
            skills=skill_snapshot_entries,
        )

    logger.info("Initial setup applied for instance %s", instance_id)
    return True


async def _build_model_setup(
    session: AsyncSession,
    tenant_id: str,
    setup: Any,
) -> tuple[dict[str, Any], tuple[str, str] | None, list[tuple[str, str, str]]]:
    provider_ids = list(getattr(setup, "provider_ids", None) or [])
    providers = await _get_providers(session, tenant_id, provider_ids)
    by_id = {str(p.id): p for p in providers}
    ordered = [by_id[str(pid)] for pid in provider_ids if str(pid) in by_id]

    custom_providers: list[dict[str, Any]] = []
    name_index: dict[tuple[str, str], dict[str, str]] = {}
    for provider in ordered:
        entry = _build_custom_provider_entry(provider)
        custom_providers.append(entry)
        for model in provider.models or []:
            name_index[(provider.name, model)] = {
                "provider_name": provider.name,
                "model": model,
                "base_url": provider.base_url,
                "api_key": provider.api_key or "",
            }

    config: dict[str, Any] = {"custom_providers": custom_providers}
    main_assignment: tuple[str, str] | None = None
    main_model = getattr(setup, "main_model", None)
    if main_model is not None:
        target = name_index.get((main_model.provider, main_model.model))
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"主模型 {main_model.provider}/{main_model.model} 未在选中的 provider 中",
            )
        config["model"] = {
            "default": target["model"],
            "provider": target["provider_name"],
            "base_url": target["base_url"],
            "api_key": target["api_key"],
        }
        main_assignment = (target["provider_name"], target["model"])

    aux_models: list[tuple[str, str, str]] = []
    seen_tasks: set[str] = set()
    for aux in list(getattr(setup, "auxiliary_models", None) or []):
        if aux.task in seen_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"辅助任务 {aux.task} 重复",
            )
        seen_tasks.add(aux.task)
        if aux.provider == "auto":
            aux_models.append((aux.task, "auto", ""))
            continue
        target = name_index.get((aux.provider, aux.model))
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"辅助任务 {aux.task} 引用的 {aux.provider}/{aux.model} 未在选中的 provider 中",
            )
        aux_models.append((aux.task, target["provider_name"], target["model"]))
    return config, main_assignment, aux_models


async def _get_providers(
    session: AsyncSession, tenant_id: str, provider_ids: list[UUID]
) -> list[Provider]:
    if not provider_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请选择至少一个 Provider"
        )
    stmt = select(Provider).where(
        Provider.tenant_id == tenant_id, Provider.id.in_(provider_ids)
    )
    providers = list((await session.execute(stmt)).scalars().all())
    if len(providers) != len(set(provider_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="部分 provider 不存在或不属于当前租户",
        )
    return providers


def _merge_skill_config(config: dict[str, Any]) -> None:
    # 技能已改为拷贝到原生扫描根 /opt/data/skills（无需 external_dirs）。
    # 这里仅透传调用方自带的 external_dirs，并清理旧 external_skill 键。
    skills_cfg = config.get("skills")
    skills_cfg = dict(skills_cfg) if isinstance(skills_cfg, dict) else {}
    external_dirs = skills_cfg.get("external_dirs")
    dirs = (
        [item for item in external_dirs if isinstance(item, str)]
        if isinstance(external_dirs, list)
        else []
    )
    if dirs:
        skills_cfg["external_dirs"] = dirs
    config["skills"] = skills_cfg
    config.pop("external_skill", None)


async def _copy_skills_to_container(
    instance_id: str,
    tenant_id: str,
    skill_slugs: list[str],
) -> list[dict[str, str]]:
    skill_service = SkillService(
        storage_root=settings.skills_storage_path,
        max_upload_size=settings.skills_max_upload_size,
    )
    records: list[dict[str, Any]] = []
    for slug in skill_slugs:
        try:
            records.append(skill_service.get_skill(slug))
        except SkillError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"技能 '{slug}' 不存在"
            ) from exc

    docker = await create_configured_docker_client(tenant_id=tenant_id)
    copied_records: list[dict[str, Any]] = []
    try:
        container_name = f"{settings.nineclaw_container_name_prefix}-{instance_id}"
        logger.info(
            "copy skills get container: instance=%s container=%s",
            instance_id,
            container_name,
        )
        container = await docker.containers.get(container_name)
        logger.info(
            "copy skills mkdir: instance=%s path=%s", instance_id, NATIVE_SKILLS_ROOT
        )
        exec_obj = await container.exec(
            ["mkdir", "-p", NATIVE_SKILLS_ROOT], stdout=True, stderr=True
        )
        async with exec_obj.start(detach=False) as stream:
            while await stream.read_out() is not None:
                pass

        # 实例内已存在的技能（含镜像内置技能）：同名跳过不覆盖。
        find_obj = await container.exec(
            [
                "sh",
                "-c",
                f"find {NATIVE_SKILLS_ROOT} -maxdepth 3 -name SKILL.md 2>/dev/null",
            ],
            stdout=True,
            stderr=True,
        )
        chunks: list[str] = []
        async with find_obj.start(detach=False) as stream:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                chunks.append(msg.data.decode(errors="replace"))
        existing_slugs: set[str] = set()
        for line in "".join(chunks).splitlines():
            line = line.strip()
            suffix = "/SKILL.md"
            if not line.endswith(suffix):
                continue
            slug = line[: -len(suffix)].rsplit("/", 1)[-1]
            if slug:
                existing_slugs.add(slug)

        storage_root = Path(skill_service.storage_root)
        for record in records:
            slug = record["id"]
            if slug in existing_slugs:
                logger.info(
                    "copy skill skipped (already exists): instance=%s slug=%s",
                    instance_id,
                    slug,
                )
                continue
            src = storage_root / slug
            logger.info(
                "copy skill archive: instance=%s slug=%s src=%s", instance_id, slug, src
            )
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                tar.add(str(src), arcname=slug)
            await container.put_archive(NATIVE_SKILLS_ROOT, buf.getvalue())
            copied_records.append(record)
            logger.info(
                "copy skill done: instance=%s slug=%s bytes=%d",
                instance_id,
                slug,
                len(buf.getvalue()),
            )

        # 属主修正：put_archive 写入的文件归 root，而实例 webui 以 hermes
        # 用户运行，无权限删除/移动这些技能（报 500 PermissionError）。
        # 把新写入的目录属主对齐技能根目录。
        if copied_records:
            chown_targets = " ".join(
                shlex.quote(f"{NATIVE_SKILLS_ROOT}/{record['id']}")
                for record in copied_records
            )
            fix_owner_cmd = (
                f"OW=$(stat -c %u:%g {NATIVE_SKILLS_ROOT}) && "
                f'chown -R "$OW" {chown_targets}'
            )
            exec_obj = await container.exec(
                ["sh", "-c", fix_owner_cmd], stdout=True, stderr=True
            )
            async with exec_obj.start(detach=False) as stream:
                while await stream.read_out() is not None:
                    pass
    finally:
        await docker.close()
    return [
        {
            "slug": str(record["id"]),
            "name": str(record.get("name") or record["id"]),
        }
        for record in copied_records
    ]


async def _build_mcp_entries(
    session: AsyncSession,
    tenant_id: str,
    mcp_ids: list[UUID],
    tools_config: Any,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    stmt = select(McpServer).where(
        McpServer.tenant_id == tenant_id, McpServer.id.in_(mcp_ids)
    )
    mcps = list((await session.execute(stmt)).scalars().all())
    if len(mcps) != len(set(mcp_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="部分 MCP 不存在或不属于当前租户",
        )
    by_id = {m.id: m for m in mcps}
    tools_map = {str(item.mcp_id): item.enabled_tools for item in (tools_config or [])}
    ordered_mcps = [by_id[mcp_id] for mcp_id in mcp_ids if mcp_id in by_id]
    return (
        {
            mcp.name: _build_hermes_mcp_entry(
                mcp,
                tools_map.get(str(mcp.id)),
            )
            for mcp in ordered_mcps
        },
        [
            {"id": str(mcp.id), "name": mcp.name, "enabled": bool(mcp.enabled)}
            for mcp in ordered_mcps
        ],
    )


def _is_sse_url(url: str | None) -> bool:
    """Detect legacy SSE MCP endpoints whose URL path ends with ``/sse``
    (query strings and trailing slashes ignored). Keep in sync with
    ``app.api.routes.mcp_servers._is_sse_url``."""
    if not url:
        return False
    path = url.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.lower().endswith("/sse")


def _build_hermes_mcp_entry(
    server: McpServer, tools_override: list[str] | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {}

    if server.transport == "stdio":
        entry["command"] = server.command
        entry["args"] = _normalize_stdio_args(server.args)
        if server.env:
            entry["env"] = dict(server.env)
    elif server.transport == "url":
        entry["url"] = server.url
        if server.headers:
            entry["headers"] = dict(server.headers)
        entry["sampling"] = {"enabled": False}
        if _is_sse_url(server.url):
            entry["transport"] = "sse"

    if server.timeout is not None:
        entry["timeout"] = server.timeout
    if server.connect_timeout is not None:
        entry["connect_timeout"] = server.connect_timeout
    if not server.enabled:
        entry["enabled"] = False

    if tools_override is not None:
        all_tool_names = [t["name"] for t in (server.tools or [])]
        excluded = [n for n in all_tool_names if n not in tools_override]
        if excluded:
            entry["tools"] = {"exclude": excluded}
    elif server.tool_settings:
        known_names = {t["name"] for t in (server.tools or [])}
        excluded = [
            name
            for name, enabled in server.tool_settings.items()
            if not enabled and name in known_names
        ]
        if excluded:
            entry["tools"] = {"exclude": excluded}
    return entry


def _normalize_stdio_args(args: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for arg in args or []:
        text = str(arg).strip()
        if not text:
            continue
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = [text]
        normalized.extend(parts or [text])
    return normalized


def _extract_supported_auxiliary_tasks(payload: Any) -> set[str]:
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


async def _build_knowledge_setup(
    session: AsyncSession,
    tenant_id: str,
    knowledge_ids: list[str],
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, str]]]:
    ext_cfg = await session.scalar(
        select(ExternalKnowledgeConfig).where(
            ExternalKnowledgeConfig.tenant_id == tenant_id
        )
    )
    rag_base_url, rag_api_key = resolve_ragflow_credentials(
        base_url=ext_cfg.base_url if ext_cfg else None,
        api_key=ext_cfg.api_key if ext_cfg else None,
    )
    knowledge_service = await _get_knowledge_service(session)
    name_map: dict[str, str] = {}
    knowledge_records_by_id: dict[str, dict[str, Any]] = {}
    try:
        for record in knowledge_service.list_knowledge():
            if not isinstance(record, dict):
                continue
            for key in (record.get("id"), record.get("dataset_id")):
                rid = str(key or "").strip()
                if rid:
                    knowledge_records_by_id[rid] = record
    except Exception as exc:
        logger.warning(
            "initial setup knowledge list failed while resolving names: %s", exc
        )
    for knowledge_id in knowledge_ids:
        kid = str(knowledge_id or "").strip()
        if not kid:
            continue
        record = knowledge_records_by_id.get(kid)
        if record is None:
            try:
                record = knowledge_service.get_knowledge(kid)
            except Exception as exc:
                logger.warning(
                    "initial setup knowledge name resolve failed for %s: %s",
                    kid,
                    exc,
                )
        name = record.get("name") if isinstance(record, dict) else None
        name_map[kid] = name.strip() if isinstance(name, str) and name.strip() else kid

    block: dict[str, Any] = {"dataset_ids": knowledge_ids}
    if rag_base_url:
        block["base_url"] = rag_base_url
    if rag_api_key:
        block["api_key"] = rag_api_key
    return (
        {"external_knowledge": block},
        build_rag_deploy_env(
            base_url=rag_base_url,
            api_key=rag_api_key,
            knowledge_ids=knowledge_ids,
            knowledge_name_map=name_map,
        ),
        [
            {"id": knowledge_id, "name": name_map[knowledge_id]}
            for knowledge_id in knowledge_ids
        ],
    )


def _deep_merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

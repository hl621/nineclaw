"""Instance Service Layer — business logic for nineclaw instance lifecycle.

Coordinates between the database (ServiceInstance records) and DockerService
(container operations). Handles port allocation, state transitions, and
keeps DB records in sync with actual container state.

Traefik routing is handled automatically via Docker labels on containers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.datetime_utils import format_utc_z, utcnow_naive
from app.models.instance import ServiceInstance
from app.services.docker_service import DockerService, NineclawConfig
from app.services.nineclaw_bootstrap import (
    BootstrapError,
    bootstrap_instance,
    wait_until_instance_dashboard_ready,
)
from app.services.nineclaw_topology import NINECLAW_SERVICES
from app.services.instance_setup_service import (
    apply_initial_setup,
    has_initial_setup,
    summarize_initial_setup,
)
from app.services.workflow.workspace_auth import (
    WorkspaceBridgeConfigurationError,
    bridge_token_for_instance,
)

logger = logging.getLogger(__name__)

CreateProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


# Number of consecutive host ports each nineclaw instance reserves.
PORTS_PER_INSTANCE = len(NINECLAW_SERVICES)

# Sentinel template ID used until a real template system is wired up.
_DEFAULT_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Process-wide lock that serialises port allocation. Without this, two
# concurrent create_instance calls in the same process can race and pick
# the same host_port_start. (Multi-process deploys still need a DB lock.)
_PORT_ALLOCATION_LOCK = asyncio.Lock()
_CREATE_TRANSIENT_STATES = {
    "created",
    "starting",
    "bootstrapping",
    "waiting_dashboard",
    "initializing",
    "restarting",
}


def _utcnow() -> datetime:
    """Naive UTC timestamp matching the TIMESTAMP WITHOUT TIME ZONE columns
    on service_instances. asyncpg rejects tz-aware datetimes against naive
    columns, which is why we strip tzinfo here. Values are still UTC by
    convention.
    """
    return utcnow_naive()


def _create_job_config(
    *,
    job_id: str,
    stage: str,
    status: str = "running",
    error: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "job_id": job_id,
        "stage": stage,
        "status": status,
        # Explicit Z so WebUI Date parse is UTC (then shown as CST-8).
        "updated_at": format_utc_z(datetime.now(timezone.utc)),
    }
    if error:
        data["error"] = error
    return data


def _set_create_job_config(
    instance: ServiceInstance,
    *,
    job_id: str | None,
    stage: str,
    status: str = "running",
    error: str | None = None,
) -> None:
    if not job_id:
        return
    instance.config = {
        **(instance.config or {}),
        "create_job": _create_job_config(
            job_id=job_id,
            stage=stage,
            status=status,
            error=error,
        ),
    }


def _has_running_create_job(instance: ServiceInstance) -> bool:
    config = instance.config if isinstance(instance.config, dict) else {}
    create_job = config.get("create_job") if isinstance(config, dict) else None
    return isinstance(create_job, dict) and create_job.get("status") == "running"


def _build_default_env() -> dict[str, str]:
    """Default environment variables baked into every nineclaw container.

    The API_SERVER_KEY is sourced from settings so deployments don't ship
    with a hard-coded credential.
    """
    return {
        "API_SERVER_ENABLED": "true",
        "API_SERVER_KEY": settings.nineclaw_token,
        "API_SERVER_HOST": "0.0.0.0",
        "API_SERVER_CORS_ORIGINS": "*",
        "API_SERVER_MODEL_NAME": "nineclaw",
        "GATEWAY_ALLOW_ALL_USERS": "true",
        "HERMES_DASHBOARD": "true",
        "HERMES_DASHBOARD_HOST": "0.0.0.0",
        "HERMES_DASHBOARD_PORT": "8644",
        "HERMES_DASHBOARD_SESSION_TOKEN": settings.nineclaw_token,
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": "nineclaw",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": settings.nineclaw_token,
        "DEFAULT_AGENT_IDENTITY": "nineclaw",
        # 镜像启动脚本 21-nineclaw-skills 默认 replace 模式：每次容器启动
        # 把 /opt/data/skills 重置为镜像内置技能，会抹掉 Manager 部署/
        # 上传的技能。merge 模式保留已有技能、同时仍用种子覆盖同名内置
        # 技能（升级镜像时内置技能照常更新）。
        "NINECLAW_SKILLS_SYNC_MODE": "merge",
    }


def _build_workspace_bridge_env(instance_id: str) -> dict[str, str]:
    """Build Runtime env inherited only by the fixed workspace MCP bridge."""
    manager_url = settings.workflow_workspace_manager_url.rstrip("/")
    if not manager_url:
        return {}
    try:
        token = bridge_token_for_instance(instance_id)
    except WorkspaceBridgeConfigurationError:
        logger.warning(
            "workflow workspace bridge is disabled for instance=%s: missing secret",
            instance_id,
        )
        return {}
    return {
        "NINECLAW_MANAGER_URL": manager_url,
        "NINECLAW_WORKSPACE_INSTANCE_ID": instance_id,
        "NINECLAW_WORKSPACE_BRIDGE_TOKEN": token,
        "NINECLAW_WORKSPACE_DIR": "/tmp/nineclaw-workspace",
    }


def _persisted_instance_environment(environment: dict[str, str]) -> dict[str, str]:
    """Keep Manager-injected Workspace runtime settings out of durable config."""
    return {
        key: value
        for key, value in environment.items()
        if key != "NINECLAW_MANAGER_URL" and not key.startswith("NINECLAW_WORKSPACE_")
    }


def _with_workspace_mcp_config(
    config_overrides: dict[str, Any] | None, *, enabled: bool
) -> dict[str, Any] | None:
    if not enabled:
        return config_overrides
    result = dict(config_overrides or {})
    raw_mcp_servers = result.get("mcp_servers")
    mcp_servers = dict(raw_mcp_servers) if isinstance(raw_mcp_servers, dict) else {}
    # This patch also repairs an existing /opt/data volume whose config.yaml
    # predates the image-level workspace server registration.
    mcp_servers["workflow_workspace"] = {
        "command": "/opt/hermes/.venv/bin/python",
        "args": ["/opt/nineclaw/workspace_mcp_server.py"],
        "env": {
            "NINECLAW_MANAGER_URL": "${NINECLAW_MANAGER_URL}",
            "NINECLAW_WORKSPACE_INSTANCE_ID": "${NINECLAW_WORKSPACE_INSTANCE_ID}",
            "NINECLAW_WORKSPACE_BRIDGE_TOKEN": "${NINECLAW_WORKSPACE_BRIDGE_TOKEN}",
            "NINECLAW_WORKSPACE_DIR": "${NINECLAW_WORKSPACE_DIR}",
        },
        "timeout": 120,
        "connect_timeout": 60,
    }
    result["mcp_servers"] = mcp_servers
    return result


class InstanceNotFoundError(Exception):
    """Raised when a requested instance does not exist."""


class InstanceConflictError(Exception):
    """Raised when an operation conflicts with the current instance state."""


class PortAllocationError(Exception):
    """Raised when no free ports are available in the configured range."""


class InstanceService:
    """Manages the full lifecycle of nineclaw service instances.

    Traefik routing is automatic via Docker labels on containers,
    no manual route registration needed.
    """

    def __init__(
        self,
        session: AsyncSession,
        docker_service: DockerService,
    ) -> None:
        self._session = session
        self._docker = docker_service

    # ─── Create ──────────────────────────────────────────────────────────

    async def create_instance(
        self,
        name: str,
        image: str,
        tenant_id: str | None = None,
        environment: dict[str, str] | None = None,
        volumes: list[str] | None = None,
        memory_limit: str | None = None,
        cpu_limit: float | None = None,
        config_overrides: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
        initial_setup: Any | None = None,
        progress: CreateProgressCallback | None = None,
        create_job_id: str | None = None,
    ) -> ServiceInstance:
        """Create a new nineclaw instance: DB record + Docker container.

        Allocates a free port block, creates the container, and persists
        the instance record with container_id and port_mappings.

        After the container starts, pushes the predefined model config and
        env vars (settings.nineclaw_default_config / nineclaw_default_env,
        merged with the per-request overrides) to the container's
        dashboard so the instance is immediately usable.
        """
        instance_id = _generate_instance_id()
        tenant_id = tenant_id or settings.default_tenant_id
        memory_limit = memory_limit or settings.nineclaw_default_memory
        cpu_limit = (
            cpu_limit if cpu_limit is not None else settings.nineclaw_default_cpus
        )
        initial_setup_summary = summarize_initial_setup(initial_setup)
        image_ref = (image or "").strip()
        if not image_ref:
            raise ValueError("image is required")
        repo = settings.nineclaw_image_repository.strip()
        if repo and not (
            image_ref == repo or image_ref.startswith(f"{repo}:")
        ):
            raise ValueError(
                f"image must belong to repository '{repo}', got '{image_ref}'"
            )

        # Fail before port allocation / DB flush so missing images do not
        # leave orphan instance rows or hang create-stream on remote inspect.
        await self._docker.ensure_image_available(image_ref)

        # Reject duplicate name within the same tenant before allocating any
        # resources. The DB-level UNIQUE constraint is the backstop; this
        # check yields a clean 409 instead of a raw IntegrityError.
        existing_stmt = select(ServiceInstance).where(
            ServiceInstance.tenant_id == tenant_id,
            ServiceInstance.name == name.strip(),
        )
        existing = (await self._session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            raise InstanceConflictError(f"智能体 '{name.strip()}' 已存在")

        async def report(stage: str, **payload: Any) -> None:
            logger.info(
                "create_instance stage: instance=%s stage=%s payload=%s",
                instance_id,
                stage,
                payload,
            )
            if progress is None:
                return
            await progress(
                stage,
                {
                    "instance_id": instance_id,
                    "job_id": create_job_id,
                    "stage": stage,
                    **payload,
                },
            )

        await report("allocating", name=name)
        logger.info(
            "create_instance begin: instance=%s tenant=%s name=%s memory=%s cpus=%s setup=%s",
            instance_id,
            tenant_id,
            name,
            memory_limit,
            cpu_limit,
            initial_setup_summary,
        )

        # Serialise port allocation against concurrent create_instance calls
        # in this process; the DB row is also persisted under the lock so
        # the next caller sees the reservation.
        async with _PORT_ALLOCATION_LOCK:
            host_port_start = await self._allocate_ports()

            # User-provided environment may not replace the Manager-issued
            # instance identity or scoped bridge credential.
            workspace_env = _build_workspace_bridge_env(instance_id)
            user_environment = dict(environment or {})
            env = {
                **_build_default_env(),
                **user_environment,
                **workspace_env,
            }
            vols = list(volumes or [])
            port_mappings = _build_port_mappings(host_port_start)

            now = _utcnow()
            instance_config: dict[str, Any] = {
                "image": image_ref,
                "network": settings.nineclaw_network,
                "environment": _persisted_instance_environment(user_environment),
                "volumes": vols,
                "host_port_start": host_port_start,
                "memory_limit": memory_limit,
                "cpu_limit": cpu_limit,
            }
            if initial_setup_summary:
                instance_config["initial_setup"] = {
                    "status": "pending",
                    **initial_setup_summary,
                }
            if create_job_id:
                instance_config["create_job"] = _create_job_config(
                    job_id=create_job_id,
                    stage="allocating",
                )

            instance = ServiceInstance(
                id=instance_id,
                tenant_id=tenant_id,
                template_id=_DEFAULT_TEMPLATE_ID,
                name=name,
                desired_state="running",
                actual_state="created",
                config=instance_config,
                port_mappings=port_mappings,
                network_name=settings.nineclaw_network,
                health_status="unknown",
                created_at=now,
                updated_at=now,
            )
            self._session.add(instance)
            # Flush so subsequent _allocate_ports() in another coroutine
            # sees this reservation via SELECT.
            await self._session.flush()

        logger.info(
            "Creating instance: id=%s, name=%s, ports=%d+",
            instance_id,
            name,
            host_port_start,
        )
        await report("creating_container", host_port_start=host_port_start)

        docker_config = NineclawConfig(
            instance_id=instance_id,
            name=name,
            host_port_start=host_port_start,
            environment=env,
            volumes=vols,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
            image=image_ref,
        )
        container_id = await self._docker.create_nineclaw(docker_config)
        logger.info(
            "create_instance docker created: instance=%s container=%s",
            instance_id,
            container_id,
        )
        instance.container_id = container_id
        instance.actual_state = "starting"
        _set_create_job_config(
            instance,
            job_id=create_job_id,
            stage="starting_container",
        )
        instance.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(instance)
        await report("starting_container", container_id=container_id)
        await self._docker.start_container(container_id)
        logger.info(
            "create_instance docker started: instance=%s container=%s",
            instance_id,
            container_id,
        )

        instance.actual_state = "bootstrapping"
        _set_create_job_config(
            instance,
            job_id=create_job_id,
            stage="waiting_dashboard",
        )
        instance.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(instance)

        logger.info(
            "Instance created and running: id=%s, container=%s",
            instance_id,
            container_id[:12],
        )
        await report("waiting_dashboard", container_id=container_id)

        # Push predefined model config + env over the dashboard so the
        # instance is immediately usable. Failure here doesn't roll back —
        # the container is left running so the operator can inspect logs
        # and retry, and DELETE still cleans up cleanly.
        try:
            await report("bootstrapping")
            await bootstrap_instance(
                instance_id,
                config_overrides=_with_workspace_mcp_config(
                    config_overrides, enabled=bool(workspace_env)
                ),
                env_overrides=env_overrides,
                restart_gateway=False if has_initial_setup(initial_setup) else None,
            )
            logger.info("create_instance bootstrap complete: instance=%s", instance_id)
        except BootstrapError as exc:
            _set_create_job_config(
                instance,
                job_id=create_job_id,
                stage="failed",
                status="failed",
                error=str(exc),
            )
            instance.health_status = "unhealthy"
            instance.error_message = f"bootstrap failed: {exc}"
            instance.updated_at = _utcnow()
            await self._session.commit()
            await self._session.refresh(instance)
            logger.error("Bootstrap failed for instance %s: %s", instance_id, exc)
            raise

        try:
            if has_initial_setup(initial_setup):
                instance.actual_state = "initializing"
                _set_create_job_config(
                    instance,
                    job_id=create_job_id,
                    stage="initializing",
                )
                instance.updated_at = _utcnow()
                await self._session.commit()
                await self._session.refresh(instance)
                await report("initializing")
            should_restart = await apply_initial_setup(
                instance_id=instance_id,
                tenant_id=tenant_id,
                setup=initial_setup,
                session=self._session,
                docker_service=self._docker,
                container_id=instance.container_id,
            )
            logger.info(
                "create_instance initial setup complete: instance=%s should_restart=%s",
                instance_id,
                should_restart,
            )
            if should_restart and instance.container_id:
                await report("restarting")
                instance.desired_state = "restarting"
                instance.actual_state = "restarting"
                _set_create_job_config(
                    instance,
                    job_id=create_job_id,
                    stage="restarting",
                )
                instance.updated_at = _utcnow()
                await self._session.commit()
                await self._session.refresh(instance)
                await self._docker.restart_container(instance.container_id)
                logger.info(
                    "create_instance restart complete: instance=%s container=%s",
                    instance_id,
                    instance.container_id,
                )
                await report("waiting_dashboard", container_id=instance.container_id)
                await wait_until_instance_dashboard_ready(instance_id)
                logger.info(
                    "create_instance dashboard ready after restart: instance=%s",
                    instance_id,
                )
                instance.desired_state = "running"
                instance.actual_state = "running"
            _set_create_job_config(
                instance,
                job_id=create_job_id,
                stage="running",
                status="succeeded",
            )
            if initial_setup_summary:
                instance.config = {
                    **(instance.config or {}),
                    "initial_setup": {
                        "status": "applied",
                        **initial_setup_summary,
                    },
                }
        except Exception as exc:
            _set_create_job_config(
                instance,
                job_id=create_job_id,
                stage="failed",
                status="failed",
                error=str(exc),
            )
            if initial_setup_summary:
                instance.config = {
                    **(instance.config or {}),
                    "initial_setup": {
                        "status": "failed",
                        "error": str(exc),
                        **initial_setup_summary,
                    },
                }
            instance.health_status = "unhealthy"
            instance.error_message = f"initial setup failed: {exc}"
            instance.updated_at = _utcnow()
            await self._session.commit()
            await self._session.refresh(instance)
            logger.error("Initial setup failed for instance %s: %s", instance_id, exc)
            raise

        instance.health_status = "healthy"
        instance.desired_state = "running"
        instance.actual_state = "running"
        _set_create_job_config(
            instance,
            job_id=create_job_id,
            stage="running",
            status="succeeded",
        )
        instance.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(instance)
        await report("running")
        logger.info("create_instance finished healthy: instance=%s", instance_id)

        return instance

    # ─── Start ───────────────────────────────────────────────────────────

    async def start_instance(self, instance_id: str) -> ServiceInstance:
        """Start a stopped instance."""
        instance = await self._get_or_raise(instance_id)

        if instance.actual_state == "running":
            raise InstanceConflictError(f"Instance {instance_id} is already running")

        instance.desired_state = "running"
        instance.updated_at = _utcnow()

        if instance.container_id:
            await self._docker.start_container(instance.container_id)
            instance.actual_state = "running"
            instance.updated_at = _utcnow()

        await self._session.commit()
        await self._session.refresh(instance)
        logger.info("Instance started: %s", instance_id)
        return instance

    # ─── Stop ────────────────────────────────────────────────────────────

    async def stop_instance(self, instance_id: str) -> ServiceInstance:
        """Stop a running instance."""
        instance = await self._get_or_raise(instance_id)

        if instance.actual_state == "exited":
            raise InstanceConflictError(f"Instance {instance_id} is already stopped")

        instance.desired_state = "stopped"
        instance.updated_at = _utcnow()

        if instance.container_id:
            await self._docker.stop_container(instance.container_id)
            instance.actual_state = "exited"
            instance.updated_at = _utcnow()

        await self._session.commit()
        await self._session.refresh(instance)
        logger.info("Instance stopped: %s", instance_id)
        return instance

    # ─── Restart ─────────────────────────────────────────────────────────

    async def restart_instance(self, instance_id: str) -> ServiceInstance:
        """Restart an instance."""
        instance = await self._get_or_raise(instance_id)

        instance.desired_state = "restarting"
        instance.actual_state = "restarting"
        instance.updated_at = _utcnow()
        await self._session.flush()

        if instance.container_id:
            await self._docker.restart_container(instance.container_id)

        instance.desired_state = "running"
        instance.actual_state = "running"
        instance.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(instance)
        logger.info("Instance restarted: %s", instance_id)
        return instance

    # ─── Delete ──────────────────────────────────────────────────────────

    async def delete_instance(self, instance_id: str) -> None:
        """Delete an instance: remove the Docker container and DB record."""
        instance = await self._get_or_raise(instance_id)

        instance.desired_state = "removed"
        instance.updated_at = _utcnow()
        await self._session.flush()

        if instance.container_id:
            try:
                await self._docker.remove_container(instance.container_id, force=True)
            except Exception as exc:
                logger.warning(
                    "Failed to remove container %s for instance %s: %s",
                    instance.container_id[:12],
                    instance_id,
                    exc,
                )

        await self._session.delete(instance)
        await self._session.commit()
        logger.info("Instance deleted: %s", instance_id)

    # ─── Query ───────────────────────────────────────────────────────────

    async def get_instance(
        self, instance_id: str, refresh: bool = True
    ) -> ServiceInstance:
        """Get instance details, refreshing actual_state from Docker."""
        instance = await self._get_or_raise(instance_id)

        if refresh and instance.container_id:
            try:
                live_status = await self._docker.get_container_status(
                    instance.container_id
                )
                if live_status != instance.actual_state and not (
                    instance.actual_state in _CREATE_TRANSIENT_STATES
                    and _has_running_create_job(instance)
                ):
                    instance.actual_state = live_status
                    instance.updated_at = _utcnow()
                    await self._session.commit()
                    await self._session.refresh(instance)
            except Exception as exc:
                logger.warning(
                    "Could not refresh container status for instance %s: %s",
                    instance_id,
                    exc,
                )

        return instance

    async def update_instance(
        self,
        instance_id: str,
        *,
        name: str | None = None,
        memory_limit: str | None = None,
        cpu_limit: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> ServiceInstance:
        """Update persisted instance metadata (name, resource limits, env)."""
        instance = await self._get_or_raise(instance_id)
        if name is not None and name.strip() != instance.name:
            clash_stmt = select(ServiceInstance).where(
                ServiceInstance.tenant_id == instance.tenant_id,
                ServiceInstance.name == name.strip(),
                ServiceInstance.id != instance_id,
            )
            clash = (await self._session.execute(clash_stmt)).scalar_one_or_none()
            if clash is not None:
                raise InstanceConflictError(f"智能体 '{name.strip()}' 已存在")
            instance.name = name.strip()
        config = dict(instance.config or {})
        if memory_limit is not None:
            config["memory_limit"] = memory_limit
        if cpu_limit is not None:
            config["cpu_limit"] = cpu_limit
        if environment is not None:
            config["environment"] = _persisted_instance_environment(environment)
        instance.config = config
        instance.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(instance)
        return instance

    async def list_instances(
        self, tenant_id: str | None = None
    ) -> list[ServiceInstance]:
        """List instances, optionally filtered by tenant.

        Refreshes actual_state from Docker in a single batch call instead
        of one inspect per instance.
        """
        stmt = select(ServiceInstance)
        if tenant_id is not None:
            stmt = stmt.where(ServiceInstance.tenant_id == tenant_id)
        stmt = stmt.order_by(ServiceInstance.created_at.desc())

        result = await self._session.execute(stmt)
        instances = list(result.scalars().all())

        if not instances:
            return instances

        # One Docker API call returns the status of all managed containers.
        live_statuses = await self._docker.get_managed_container_statuses()
        dirty = False
        now = _utcnow()
        for instance in instances:
            if not instance.container_id:
                continue
            live = live_statuses.get(instance.container_id)
            if (
                live is not None
                and live != instance.actual_state
                and not (
                    instance.actual_state in _CREATE_TRANSIENT_STATES
                    and _has_running_create_job(instance)
                )
            ):
                instance.actual_state = live
                instance.updated_at = now
                dirty = True

        if dirty:
            await self._session.commit()

        return instances

    # ─── Internal helpers ─────────────────────────────────────────────────

    async def _get_or_raise(self, instance_id: str) -> ServiceInstance:
        """Fetch an instance by ID or raise InstanceNotFoundError."""
        result = await self._session.execute(
            select(ServiceInstance).where(ServiceInstance.id == instance_id)
        )
        instance = result.scalar_one_or_none()
        if instance is None:
            raise InstanceNotFoundError(f"Instance '{instance_id}' not found")
        return instance

    async def _allocate_ports(self) -> int:
        """Find the lowest free host_port_start in the configured range.

        Caller is responsible for holding _PORT_ALLOCATION_LOCK so the
        result is still free when the caller persists its reservation.
        """
        result = await self._session.execute(select(ServiceInstance.config))
        used_starts: set[int] = set()
        for (config,) in result:
            if isinstance(config, dict) and "host_port_start" in config:
                used_starts.add(int(config["host_port_start"]))

        port = settings.nineclaw_port_range_start
        while port + PORTS_PER_INSTANCE - 1 <= settings.nineclaw_port_range_end:
            if port not in used_starts:
                return port
            port += PORTS_PER_INSTANCE

        raise PortAllocationError(
            f"No free port blocks available in range "
            f"{settings.nineclaw_port_range_start}-{settings.nineclaw_port_range_end}"
        )


# ─── Module-level helpers ─────────────────────────────────────────────────────


def _generate_instance_id() -> str:
    """Generate a short unique instance ID."""
    return uuid.uuid4().hex[:16]


def _build_port_mappings(host_port_start: int) -> dict[str, dict[str, int]]:
    """Build the port_mappings dict stored in the DB.

    Maps service names to host/container port pairs.
    """
    mappings: dict[str, dict[str, int]] = {}
    for i, svc in enumerate(NINECLAW_SERVICES):
        mappings[svc.name] = {
            "host_port": host_port_start + i,
            "container_port": svc.internal_port,
        }
    return mappings

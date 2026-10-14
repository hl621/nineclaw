"""Docker Service Layer — Core container operations via Docker Engine API.

Uses aiodocker to communicate with the Docker Engine for creating, starting,
stopping, restarting, removing, and inspecting nineclaw containers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from app.core.config import settings
from app.services.docker_client import (
    create_configured_docker_client,
    mask_docker_url,
    resolve_docker_url,
)
from app.services.nineclaw_topology import NINECLAW_SERVICES, render_route

logger = logging.getLogger(__name__)


# Label keys are derived from the configured prefix so deployments can
# coexist with other Docker-managed stacks without colliding on labels.
LABEL_INSTANCE_ID = f"{settings.nineclaw_label_prefix}.instance_id"
LABEL_MANAGED = f"{settings.nineclaw_label_prefix}.managed"
LABEL_NAME = f"{settings.nineclaw_label_prefix}.name"


@dataclass
class NineclawConfig:
    """Configuration for creating a nineclaw container instance."""

    instance_id: str
    name: str
    host_port_start: int
    environment: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    memory_limit: str = field(default_factory=lambda: settings.nineclaw_default_memory)
    cpu_limit: float = field(default_factory=lambda: settings.nineclaw_default_cpus)
    image: str = ""
    network: str = field(default_factory=lambda: settings.nineclaw_network)
    shm_size: str = field(default_factory=lambda: settings.nineclaw_shm_size)


class DockerService:
    """Manages Docker container operations through the Docker Engine API."""

    def __init__(self, docker: aiodocker.Docker | None = None) -> None:
        self._docker = docker
        self._owns_client = docker is None

    async def connect(self) -> None:
        """Initialize the Docker client connection."""
        if self._docker is None:
            self._docker = await create_configured_docker_client()
            self._owns_client = True
        docker_url, _ = await resolve_docker_url()
        logger.info("Docker client connected via %s", mask_docker_url(docker_url))

    async def close(self) -> None:
        """Close the Docker client connection."""
        if self._docker and self._owns_client:
            await self._docker.close()
            self._docker = None
        logger.info("Docker client connection closed")

    @property
    def client(self) -> aiodocker.Docker:
        """Get the underlying Docker client, raising if not connected."""
        if self._docker is None:
            raise RuntimeError("DockerService is not connected. Call connect() first.")
        return self._docker

    async def list_nineclaw_images(
        self,
        repository: str | None = None,
    ) -> list[dict[str, Any]]:
        """List local NineClaw image tags, highest version first.

        Filters Docker images by repository name (default from settings),
        expands each matching RepoTag into one version entry, and sorts by
        semantic version descending (e.g. v2026.7.20 > v2026.7.7.2 > v2026.7.1).

        Falls back to ``docker images`` over SSH when aiodocker's SSH unix
        tunnel is unavailable (common on Windows hosts).
        """
        repo = (repository or settings.nineclaw_image_repository).strip()
        if not repo:
            raise ValueError("Nineclaw image repository is not configured")

        try:
            return await self._list_nineclaw_images_aiodocker(repo)
        except Exception as exc:
            logger.warning(
                "aiodocker image list failed (%s); trying SSH CLI fallback",
                exc,
            )
            fallback = await self._list_nineclaw_images_ssh_cli(repo)
            if fallback is not None:
                return fallback
            raise

    async def _list_nineclaw_images_aiodocker(self, repo: str) -> list[dict[str, Any]]:
        raw_images = await self.client.images.list(filters={"reference": [repo]})
        return _normalize_nineclaw_image_versions(raw_images, repo)

    async def _list_nineclaw_images_ssh_cli(self, repo: str) -> list[dict[str, Any]] | None:
        from urllib.parse import unquote, urlsplit

        from app.services.docker_client import resolve_docker_url

        docker_url, _ = await resolve_docker_url()
        if not docker_url.startswith("ssh://"):
            return None

        parsed = urlsplit(docker_url)
        host = parsed.hostname
        if not host:
            return None
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        port = parsed.port or 22
        if not username:
            return None

        import asyncssh

        cmd = (
            "docker images "
            f"--filter reference={repo} "
            "--format '{{.Repository}}:{{.Tag}}\\t{{.CreatedAt}}\\t{{.ID}}'"
        )
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password or None,
            known_hosts=None,
        ) as conn:
            result = await conn.run(cmd, check=False)
        if result.exit_status not in (0, None):
            stderr = (result.stderr or "").strip()
            raise RuntimeError(stderr or f"docker images failed with status {result.exit_status}")

        versions: list[dict[str, Any]] = []
        seen: set[str] = set()
        prefix = f"{repo}:"
        stdout = result.stdout or ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            image_ref = parts[0].strip()
            if not image_ref.startswith(prefix) or image_ref.endswith(":<none>"):
                continue
            short = image_ref[len(prefix) :]
            if not _is_selectable_nineclaw_tag(short):
                continue
            if image_ref in seen:
                continue
            seen.add(image_ref)
            versions.append(
                {
                    "image": image_ref,
                    "tag": short,
                    "created": 0,
                }
            )

        # Sort tags descending so v2026.7.7.2 > v2026.7.1 > v2026.6.19
        versions.sort(key=lambda item: _version_sort_key(item["tag"]), reverse=True)
        return versions

    async def ensure_image_available(self, image: str, *, timeout: float = 10.0) -> None:
        """Fail fast if the Docker image is not present on the Engine host.

        Prefer listing known tags (works via SSH CLI fallback). Fall back to a
        timed ``images.inspect`` so remote SSH hangs do not block create-stream.
        """
        image_ref = (image or "").strip()
        if not image_ref:
            raise ValueError("Nineclaw image is required")

        try:
            repo = image_ref.split(":", 1)[0]
            items = await self.list_nineclaw_images(repository=repo)
            if any(str(item.get("image") or "") == image_ref for item in items):
                return
            raise ValueError(missing_image_message(image_ref))
        except ValueError:
            raise
        except Exception as exc:
            logger.warning(
                "image list precheck failed for %s (%s); falling back to inspect",
                image_ref,
                exc,
            )

        try:
            await asyncio.wait_for(self.client.images.inspect(image_ref), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise ValueError(missing_image_message(image_ref, timed_out=True)) from exc
        except DockerError as exc:
            message = str(getattr(exc, "message", exc)).lower()
            if (
                exc.status == 404
                or "no such image" in message
                or ("not found" in message and "image" in message)
            ):
                raise ValueError(missing_image_message(image_ref)) from exc
            raise

    # ─── Container Lifecycle ─────────────────────────────────────────────

    async def create_nineclaw(self, config: NineclawConfig) -> str:
        """Create a nineclaw container with the given configuration.

        Returns the Docker container ID.
        """
        if not (config.image or "").strip():
            raise ValueError("Nineclaw image is required")
        image = config.image.strip()
        await self.ensure_image_available(image)

        # Expose container-side ports for Traefik discovery. Host port
        # publishing is optional: Deploy reaches Runtime through Traefik on
        # qiyuan_net, while local/debug installs may opt into direct host ports.
        exposed_ports: dict[str, dict[str, Any]] = {}
        port_bindings: dict[str, list[dict[str, Any]]] = {}
        for i, svc in enumerate(NINECLAW_SERVICES):
            port_key = f"{svc.internal_port}/tcp"
            exposed_ports[port_key] = {}
            if settings.nineclaw_publish_host_ports:
                host_port = config.host_port_start + i
                port_bindings[port_key] = [{"HostPort": str(host_port)}]

        env_list = [f"{k}={v}" for k, v in config.environment.items()]

        labels = self._build_traefik_labels(config.instance_id, config.name)

        memory_bytes = _parse_memory_string(config.memory_limit)

        # Container configuration following Docker Engine API format.
        # Note: use the default bridge network so port bindings work, then
        # connect to the custom network separately after creation.
        host_config: dict[str, Any] = {
            "Binds": config.volumes,
            "Memory": memory_bytes,
            "NanoCpus": int(config.cpu_limit * 1e9),
            "ShmSize": _parse_memory_string(config.shm_size),
            "RestartPolicy": {"Name": settings.nineclaw_restart_policy},
            "Ulimits": [
                {"Name": "stack", "Soft": 67108864, "Hard": 67108864},
                {"Name": "memlock", "Soft": -1, "Hard": -1},
            ],
        }
        if port_bindings:
            host_config["PortBindings"] = port_bindings

        container_config: dict[str, Any] = {
            "Image": image,
            "Cmd": settings.nineclaw_command,
            "Env": env_list,
            "ExposedPorts": exposed_ports,
            "Labels": labels,
            "HostConfig": host_config,
        }

        container_name = (
            f"{settings.nineclaw_container_name_prefix}-{config.instance_id}"
        )

        logger.info(
            "Creating nineclaw container: name=%s, ports=%d-%d, image=%s",
            container_name,
            config.host_port_start,
            config.host_port_start + len(NINECLAW_SERVICES) - 1,
            image,
        )

        container = await self.client.containers.create(
            config=container_config, name=container_name
        )
        container_id = container.id

        # Connect to the custom network after creation (avoids NetworkMode conflict)
        if config.network and config.network != "bridge":
            try:
                network = await self.client.networks.get(config.network)
                await network.connect({"Container": container_id})
                logger.info(
                    "Container %s connected to network %s",
                    container_id[:12],
                    config.network,
                )
            except Exception as exc:
                logger.warning(
                    "Could not connect container %s to network %s: %s",
                    container_id[:12],
                    config.network,
                    exc,
                )

        logger.info(
            "Container created: id=%s, instance_id=%s",
            container_id[:12],
            config.instance_id,
        )
        return container_id

    @staticmethod
    def _build_traefik_labels(instance_id: str, container_name: str) -> dict[str, str]:
        """Build the full Docker label set: management labels + Traefik routing.

        Each nineclaw service gets:
          - a Traefik router matching the rendered PathPrefix
          - a stripprefix middleware
          - gateway: an inject-auth middleware that adds
            ``Authorization: Bearer {nineclaw_token}``.
          - dashboard: an inject-auth middleware that adds
            ``X-Hermes-Session-Token: {nineclaw_token}`` for the
            NineClaw-patched Runtime dashboard gate.
          - a CORS-allow middleware (shared across this instance's services)
            that echoes any request Origin back as
            ``Access-Control-Allow-Origin`` and answers OPTIONS preflight at
            the proxy. This effectively *disables* same-origin restrictions
            for the nineclaw-runtime so browsers stop blocking cross-site
            requests against ``/traefik/nineclaw/{id}/...``.

        Order on each router is ``cors → stripprefix → [injectauth?]``. CORS
        is first so that:
          - OPTIONS preflight is short-circuited by Traefik (returns 204
            with the allow headers) before reaching the upstream, and
          - the response headers are added on the way back regardless of
            what the upstream returned (Traefik's headers middleware also
            takes precedence over upstream-supplied CORS headers).
        """
        labels: dict[str, str] = {
            LABEL_INSTANCE_ID: instance_id,
            LABEL_MANAGED: "true",
            LABEL_NAME: container_name,
            "traefik.enable": "true",
        }

        # Per-instance permissive CORS middleware.
        #
        # Traefik's ``headers`` middleware *adds* its CORS response headers
        # without first stripping anything the upstream may have set. If
        # nineclaw-runtime emits its own ``Access-Control-Allow-Origin: *``,
        # the response that reaches the browser ends up with two values
        # ("\*, http://localhost:5173") and the browser rejects the
        # response with "header contains multiple values".
        #
        # Fix: in the *same* middleware, set every CORS allow-* response
        # header to the empty string via ``customResponseHeaders`` so the
        # upstream copy is removed, then let ``accessControlAllow*`` write
        # the single canonical version. Traefik applies
        # ``customResponseHeaders`` first and ``accessControlAllow*`` last
        # on the response path, so the final headers are exactly the ones
        # we configured here.
        #
        # ``accessControlAllowOriginListRegex=".*"`` echoes the request
        # Origin back (not the literal "*"); echoing is the only
        # configuration compatible with ``allow-credentials: true`` —
        # browsers reject ``*`` combined with credentials.
        mw_cors = f"nineclaw-{instance_id}-cors"
        upstream_cors_headers_to_strip = (
            "Access-Control-Allow-Origin",
            "Access-Control-Allow-Methods",
            "Access-Control-Allow-Headers",
            "Access-Control-Allow-Credentials",
            "Access-Control-Expose-Headers",
            "Access-Control-Max-Age",
            # Vary is rewritten below via ``addVaryHeader`` so wipe any
            # upstream copy too — otherwise we'd end up with two Vary
            # headers, one of which may not include "Origin".
            "Vary",
        )
        for header in upstream_cors_headers_to_strip:
            labels[
                f"traefik.http.middlewares.{mw_cors}.headers.customResponseHeaders.{header}"
            ] = ""

        labels.update(
            {
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlAllowOriginListRegex": ".*",
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlAllowMethods": "GET,POST,PUT,PATCH,DELETE,OPTIONS,HEAD",
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlAllowHeaders": "*",
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlExposeHeaders": "*",
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlAllowCredentials": "true",
                f"traefik.http.middlewares.{mw_cors}.headers.accessControlMaxAge": "86400",
                f"traefik.http.middlewares.{mw_cors}.headers.addVaryHeader": "true",
            }
        )

        for svc in NINECLAW_SERVICES:
            prefix = render_route(svc.route_template, instance_id)
            router_name = f"nineclaw-{instance_id}-{svc.name}"
            mw_strip = f"{router_name}-stripprefix"
            mw_auth = f"{router_name}-injectauth"

            # cors must be first so OPTIONS preflight is handled at the
            # proxy and so its response headers win over any CORS headers
            # the upstream might emit. Then stripprefix rewrites the path
            # before the upstream call, and injectauth (when needed) adds
            # the service-specific auth header.
            middlewares = [mw_cors, mw_strip]

            labels.update(
                {
                    f"traefik.http.routers.{router_name}.rule": f"PathPrefix(`{prefix}/`)",
                    f"traefik.http.routers.{router_name}.entrypoints": settings.traefik_entrypoint,
                    f"traefik.http.routers.{router_name}.service": router_name,
                    f"traefik.http.services.{router_name}.loadbalancer.server.port": str(
                        svc.internal_port
                    ),
                    f"traefik.http.middlewares.{mw_strip}.stripprefix.prefixes": f"{prefix}/",
                }
            )

            if svc.name == "gateway":
                labels[
                    f"traefik.http.middlewares.{mw_auth}.headers.customrequestheaders.Authorization"
                ] = f"Bearer {settings.nineclaw_token}"
                middlewares.append(mw_auth)
            elif svc.name == "dashboard":
                labels[
                    f"traefik.http.middlewares.{mw_auth}.headers.customrequestheaders.X-Hermes-Session-Token"
                ] = settings.nineclaw_token
                middlewares.append(mw_auth)

            labels[f"traefik.http.routers.{router_name}.middlewares"] = ",".join(
                middlewares
            )

        return labels

    async def start_container(self, container_id: str) -> None:
        """Start a stopped container."""
        container = await self.client.containers.get(container_id)
        await container.start()
        logger.info("Container started: %s", container_id[:12])

    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop a running container.

        Args:
            container_id: The Docker container ID.
            timeout: Seconds to wait before sending SIGKILL.
        """
        container = await self.client.containers.get(container_id)
        await container.stop(t=timeout)
        logger.info("Container stopped: %s", container_id[:12])

    async def restart_container(self, container_id: str, timeout: int = 10) -> None:
        """Restart a container.

        Args:
            container_id: The Docker container ID.
            timeout: Seconds to wait before sending SIGKILL during stop phase.
        """
        container = await self.client.containers.get(container_id)
        await container.restart(timeout=timeout)
        logger.info("Container restarted: %s", container_id[:12])

    async def remove_container(self, container_id: str, force: bool = True) -> None:
        """Remove a container.

        Args:
            container_id: The Docker container ID.
            force: If True, force-remove even if running.
        """
        container = await self.client.containers.get(container_id)
        await container.delete(force=force)
        logger.info("Container removed: %s (force=%s)", container_id[:12], force)

    async def get_container_status(self, container_id: str) -> str:
        """Get the current status of a container.

        Returns one of: created, running, paused, restarting, exited, removing, dead.
        """
        container = await self.client.containers.get(container_id)
        info = await container.show()
        status = info["State"]["Status"]
        logger.debug("Container %s status: %s", container_id[:12], status)
        return status

    async def get_managed_container_statuses(self) -> dict[str, str]:
        """Return a {container_id: status} map for all managed containers.

        `containers/json` already returns each container's `State.Status`,
        so this is a single Docker API round-trip — no per-container
        `inspect` follow-up. Over SSH-remote daemons each extra call is a
        full SSH round-trip, which made listing scale linearly with the
        number of instances.
        """
        try:
            containers = await self.client.containers.list(
                all=True,
                filters={"label": [f"{LABEL_MANAGED}=true"]},
            )
        except Exception as exc:
            logger.warning("Failed to list managed containers: %s", exc)
            return {}

        result: dict[str, str] = {}
        for container in containers:
            try:
                state = container._container.get("State")
                if not isinstance(state, dict):
                    continue
                status = state.get("Status")
                if status and container._id:
                    result[container._id] = status
            except Exception as exc:
                logger.debug("Skipping container during status sweep: %s", exc)
        return result

    async def stream_logs(
        self,
        container_id: str,
        follow: bool = True,
        tail: int = 100,
        stdout: bool = True,
        stderr: bool = True,
    ):
        """Stream container logs.

        Args:
            container_id: The Docker container ID.
            follow: Whether to follow log output (like -f).
            tail: Number of lines to show from the end (0 means all).
            stdout: Include stdout.
            stderr: Include stderr.

        Yields:
            Log lines as strings.
        """
        container = await self.client.containers.get(container_id)

        async for line in container.log(
            stdout=stdout,
            stderr=stderr,
            follow=follow,
            tail=tail,
        ):
            yield line

    async def exec_container_output(
        self,
        container_id: str,
        command: list[str],
        *,
        timeout: float = 5.0,
    ) -> tuple[int | None, str]:
        """Run a short non-interactive command in a container and collect output."""
        container = await self.client.containers.get(container_id)
        exec_obj = await container.exec(
            command,
            stdout=True,
            stderr=True,
            stdin=False,
            tty=False,
        )
        stream = exec_obj.start()
        chunks: list[str] = []

        async def read_all() -> None:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                chunks.append(msg.data.decode(errors="replace"))

        await asyncio.wait_for(read_all(), timeout=timeout)
        try:
            info = await exec_obj.inspect()
            exit_code = info.get("ExitCode")
        except Exception:
            exit_code = None
        return exit_code, "".join(chunks)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def missing_image_message(image: str, *, timed_out: bool = False) -> str:
    """User-facing Chinese error when a create-time image tag is missing."""
    suffix = (
        "检查镜像时超时，请确认 Docker / 远程 SSH 连接正常后重试。"
        if timed_out
        else (
            "请在部署机执行 `docker images` 确认是否已导入；"
            "若没有，请用交付包 `docker_images/` 执行 `docker load`，"
            "或检查创建时选择的镜像标签 / Manager 环境变量 `NINECLAW_IMAGE` "
            "是否与已导入镜像一致。"
        )
    )
    return f"Docker 镜像不存在：{image}。{suffix}"


def _is_selectable_nineclaw_tag(tag: str) -> bool:
    """Keep version tags (e.g. v2026.7.7.2); drop floating tags like latest."""
    t = (tag or "").strip()
    if not t or t.lower() in {"latest", "stable", "dev", "nightly"}:
        return False
    # Prefer explicit version tags used by NineClaw releases.
    if t.startswith(("v", "V")) and len(t) > 1 and t[1].isdigit():
        return True
    # Also allow pure dotted numeric tags if present.
    return t[0].isdigit() and any(ch.isdigit() for ch in t)


def _normalize_nineclaw_image_versions(
    raw_images: list[dict[str, Any]],
    repo: str,
) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    seen: set[str] = set()
    prefix = f"{repo}:"

    for img in raw_images:
        created_raw = img.get("Created") or 0
        try:
            created = int(created_raw)
        except (TypeError, ValueError):
            created = 0
        for tag in img.get("RepoTags") or []:
            if not isinstance(tag, str) or not tag.startswith(prefix):
                continue
            if tag.endswith(":<none>") or tag in seen:
                continue
            short = tag[len(prefix) :]
            if not _is_selectable_nineclaw_tag(short):
                continue
            seen.add(tag)
            versions.append(
                {
                    "image": tag,
                    "tag": short,
                    "created": created,
                }
            )

    versions.sort(
        key=lambda item: (
            _version_sort_key(str(item["tag"])),
            int(item.get("created") or 0),
        ),
        reverse=True,
    )
    return versions


def _version_sort_key(tag: str) -> tuple:
    """Numeric sort key for tags like v2026.7.20 / v2026.7.7.2.

    Parts are zero-padded to a fixed length so shorter tags do not win over
    longer ones incorrectly when reverse-sorted (e.g. v2026.7.7 vs v2026.7.7.2).
    ``latest`` sorts lowest so version tags win when reverse-sorted.
    """
    if tag.lower() == "latest":
        return (-1,)
    text = tag[1:] if tag.startswith(("v", "V")) else tag
    nums: list[int] = []
    for chunk in text.replace("-", ".").split("."):
        if chunk.isdigit():
            nums.append(int(chunk))
        else:
            # Non-numeric segment: keep relative order after numeric prefix.
            nums.append(-1)
            break
    # Pad so v2026.7.7 sorts below v2026.7.7.2 under reverse=True.
    while len(nums) < 6:
        nums.append(0)
    return tuple(nums)


def _parse_memory_string(memory_str: str) -> int:
    """Parse a human-readable memory string (e.g., '4G', '512M', '2g') to bytes.

    Supports suffixes: B, K/KB, M/MB, G/GB, T/TB (case-insensitive).
    """
    memory_str = memory_str.strip().upper()

    units = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
    }

    for suffix, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if memory_str.endswith(suffix):
            number_part = memory_str[: -len(suffix)].strip()
            return int(float(number_part) * multiplier)

    # No suffix — assume bytes
    return int(memory_str)

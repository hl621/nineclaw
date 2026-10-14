"""Application configuration using Pydantic Settings."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and the .env file.

    Only fields that are actually consumed by the codebase are kept here.
    Add a new field whenever you need to expose a value to .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Database ─────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/nineclaw_manager"
    )
    database_echo: bool = False

    # ─── FastAPI ──────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    # ─── Logging ──────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ─── Jobs ─────────────────────────────────────────────────────────────
    # First implementation is in-process memory.  Keep this explicit so the
    # deployment contract can grow to redis without changing API semantics.
    job_backend: str = "memory"

    # ─── External dependency bulkheads ────────────────────────────────────
    # Queue wait is not a task runtime timeout. It only caps how long a request
    # waits for an internal dependency slot when that dependency is saturated.
    external_queue_wait_timeout_seconds: float = 1.0
    external_ragflow_max_concurrency: int = 4

    # ─── Docker engine ────────────────────────────────────────────────────
    # Default local Docker socket. Remote Docker SSH config is stored in the DB
    # from the system settings UI; the extra fields below are legacy fallbacks.
    docker_url: str = ""
    docker_api_version: str = "auto"
    docker_tls_verify: bool = False
    docker_cert_path: str = ""
    docker_socket_path: str = "/var/run/docker.sock"

    # ─── Nineclaw container topology ──────────────────────────────────────
    # The three internal ports correspond to (gateway, webui, dashboard).
    # Image tags are no longer fixed in env; create-instance picks a local
    # Docker tag for this repository (default: nineclaw) via the UI.
    nineclaw_image_repository: str = "nineclaw"
    nineclaw_command: list[str] = ["gateway", "run", "--replace"]
    nineclaw_network: str = "qiyuan_net"
    nineclaw_port_range_start: int = 33000
    nineclaw_port_range_end: int = 40000
    nineclaw_internal_ports: list[int] = [8642, 8643, 8644]
    nineclaw_publish_host_ports: bool = False
    nineclaw_container_name_prefix: str = "nineclaw"
    nineclaw_label_prefix: str = "orchestrator"

    # ─── Nineclaw container resource defaults ─────────────────────────────
    nineclaw_default_memory: str = "4G"
    nineclaw_default_cpus: float = 2.0
    nineclaw_shm_size: str = "2g"
    nineclaw_restart_policy: str = "unless-stopped"

    # ─── Tenant defaults ──────────────────────────────────────────────────
    default_tenant_id: str = "default"

    # ─── Skill storage ────────────────────────────────────────────────────
    # Filesystem path used as the root of the public skill registry.
    # Each immediate subdirectory containing a SKILL.md is treated as one
    # skill. Manually dropping a folder here (or removing one) is a fully
    # supported way to add/remove a skill — the API only scans the dir
    # and never keeps a separate DB index, so the filesystem is the
    # source of truth.
    skills_storage_path: str = "./skills_storage"

    # Maximum size accepted by POST /skills/upload, in bytes. Defaults to
    # 50 MiB which is generous for a SKILL bundle (text + a few scripts).
    skills_max_upload_size: int = 50 * 1024 * 1024

    # ─── Knowledge base storage ───────────────────────────────────────────
    # Filesystem path used as the root of the RAG knowledge registry.
    # Each immediate subdirectory with a meta.json is one knowledge base.
    knowledge_storage_path: str = "./knowledge_storage"

    # Maximum size accepted by POST /knowledge/{id}/files, in bytes.
    knowledge_max_upload_size: int = 50 * 1024 * 1024

    # ─── Workflow engine ─────────────────────────────────────────────────
    workflow_artifact_storage_path: str = "./workflow_artifacts"
    workflow_artifact_max_upload_size: int = 100 * 1024 * 1024
    workflow_artifact_backend: str = "local"
    workflow_artifact_s3_endpoint_url: str = ""
    workflow_artifact_s3_bucket: str = ""
    workflow_artifact_s3_access_key_id: str = ""
    workflow_artifact_s3_secret_access_key: str = ""
    workflow_artifact_s3_region: str = "us-east-1"
    workflow_artifact_s3_prefix: str = "workflow-artifacts"
    # Historical Artifact orphans are collected conservatively. The grace
    # period covers the interval between storage durability and DB commit.
    workflow_artifact_gc_enabled: bool = True
    workflow_artifact_gc_interval_seconds: float = 60 * 60
    workflow_artifact_gc_orphan_grace_seconds: int = 24 * 60 * 60
    workflow_artifact_gc_batch_size: int = 100
    workflow_artifact_gc_max_scan_pages: int = 1000
    # Runtime-local workspace MCP bridges authenticate with a token derived
    # for exactly one ServiceInstance.  It must be a deployment secret, never
    # the shared Hermes gateway token.
    workflow_workspace_bridge_secret: str = ""
    workflow_workspace_manager_url: str = ""
    workflow_scheduler_enabled: bool = True
    workflow_scheduler_poll_seconds: float = 0.5
    workflow_job_lease_seconds: int = 60
    workflow_hermes_request_timeout: float = 20.0
    workflow_monitor_poll_seconds: float = 2.0

    # ─── Knowledge backend ────────────────────────────────────────────────
    # ``filesystem`` — local ``knowledge_storage/`` (default)
    # ``ragflow``    — proxy all knowledge APIs to RAGFlow HTTP API
    knowledge_backend: str = "filesystem"

    # Optional .env fallback for RAGFlow credentials. Per-tenant DB config
    # from the settings UI takes precedence when present.
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""

    # ─── Nineclaw token ───────────────────────────────────────────────────
    # Single token used for:
    #   1. Container API_SERVER_KEY (authenticates requests to the container)
    #   2. HERMES_DASHBOARD_SESSION_TOKEN for dashboard access
    #   3. Traefik inject-auth header for /gateway and /dashboard routes
    nineclaw_token: str = ""

    # ─── Traefik routing ──────────────────────────────────────────────────
    # {instance_id} is substituted at runtime.
    traefik_entrypoint: str = "web"
    nineclaw_route_gateway: str = "/traefik/nineclaw/{instance_id}/gateway"
    nineclaw_route_webui: str = "/traefik/nineclaw/{instance_id}/webui"
    nineclaw_route_dashboard: str = "/traefik/nineclaw/{instance_id}/dashboard"

    # Public Traefik entrypoint used for Traefik-routed NineClaw instance
    # management such as dashboard bootstrap and WebSearch runtime URLs.
    # When unset, keep the legacy internal Docker-network URL below.
    public_traefik_url: str = ""

    # URL the manager process itself uses to call Traefik. In packaged
    # Docker deployments this should be the Docker-network service URL
    # (for example http://traefik:80), while PUBLIC_TRAEFIK_URL remains the
    # browser-facing host URL used by WebUI.
    manager_traefik_url: str = ""

    # Internal URL the manager uses to reach Traefik (and through it, the
    # dashboard service of every nineclaw instance) on the shared Docker
    # network. Default points to the Traefik service name on qiyuan_net.
    traefik_internal_url: str = "http://traefik:80"

    # ─── Nineclaw bootstrap (auto-config after container start) ───────────
    # Maximum seconds to wait for the dashboard to become reachable after
    # container start. Also used as the maximum wait for gateway-restart.
    nineclaw_bootstrap_timeout: float = 60.0

    # Whether to restart the gateway after pushing config so the new model
    # selection takes effect immediately for new sessions.
    nineclaw_bootstrap_restart_gateway: bool = True

    # Default model/agent config pushed via PUT /api/config on every new
    # container. Keys use the dashboard's flat dot-notation (e.g.
    # "agent.max_turns"). Empty by default — populate via the
    # NINECLAW_DEFAULT_CONFIG env var (JSON object).
    nineclaw_default_config: dict[str, Any] = {}

    # Default environment variables pushed via PUT /api/env (one call per
    # key) on every new container — typically provider API keys such as
    # ANTHROPIC_API_KEY or OPENAI_API_KEY. Empty by default — populate via
    # the NINECLAW_DEFAULT_ENV env var (JSON object).
    nineclaw_default_env: dict[str, str] = {}

    # ─── Interactive terminal sessions ───────────────────────────────────
    # Terminal sessions stay alive while a browser tab is attached. Closing
    # the modal keeps the attachment open, but closing the page/browser detaches
    # it and the session is released after a short grace period.
    terminal_max_sessions_per_instance: int = 6
    terminal_idle_timeout_seconds: int = 60
    terminal_cleanup_interval_seconds: int = 15
    terminal_resize_timeout_seconds: float = 1.0

    # ─── Default custom (OpenAI-compatible) provider ──────────────────────
    # If NAME + BASE_URL + API_KEY + MODEL are all set, the bootstrap step
    # appends a custom_providers[] entry to the pushed config and selects
    # "{NAME}/{MODEL}" as the default model. Leave NAME blank to disable.
    nineclaw_custom_provider_name: str = ""
    nineclaw_custom_provider_base_url: str = ""
    nineclaw_custom_provider_api_key: str = ""
    nineclaw_custom_provider_model: str = ""

    # ─── CORS ─────────────────────────────────────────────────────────────
    # ``cors_origin_regex`` takes precedence over ``cors_origins`` when set:
    # Starlette will echo the matching request Origin back instead of the
    # literal "*", which is the only configuration that is compatible with
    # ``allow_credentials=True`` (browsers reject the wildcard combined
    # with credentials). The default ``.*`` therefore disables every
    # browser-side cross-origin restriction against the manager API.
    cors_origins: list[str] = ["*"]
    cors_origin_regex: str = ".*"
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]
    cors_expose_headers: list[str] = ["*"]
    cors_max_age: int = 86400

    # ─── Extractor sandbox (OpenSandbox) ─────────────────────────────────────
    open_sandbox_api_key: str = ""
    open_sandbox_domain: str = ""  # e.g. opensandbox-server:8090
    open_sandbox_protocol: str = "http"  # http or https
    open_sandbox_image: str = "nineclaw-sandbox:latest"
    # ─── Nineclaw Sandbox service (persistent search) ────────────────────────
    nineclaw_sandbox_url: str = "http://nineclaw-sandbox:8001"
    # WebSearch authoring/explore API. Empty means calling it through Traefik.
    websearch_api_url: str = ""

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for Alembic (replaces asyncpg with psycopg2)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def resolved_docker_url(self) -> str:
        """Docker Engine endpoint URL, falling back to the legacy socket path."""
        if self.docker_url.strip():
            return self.docker_url.strip()
        return f"unix://{self.docker_socket_path}"

    @property
    def resolved_traefik_url(self) -> str:
        """Traefik URL used by manager runtime calls, preferring PUBLIC_TRAEFIK_URL."""
        public_url = self.public_traefik_url.strip()
        internal_url = self.traefik_internal_url.strip()
        return (public_url or internal_url).rstrip("/")

    @property
    def resolved_manager_traefik_url(self) -> str:
        """Traefik URL used by manager-to-Traefik runtime calls."""
        manager_url = self.manager_traefik_url.strip()
        if manager_url:
            return manager_url.rstrip("/")
        return self.resolved_traefik_url

    @property
    def resolved_websearch_api_url(self) -> str:
        configured = self.websearch_api_url.strip()
        if configured:
            return configured.rstrip("/")
        return f"{self.resolved_manager_traefik_url}/ws-api"


settings = Settings()

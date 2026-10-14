"""Push QYRAG settings to NineClaw instances via Hermes ``PUT /api/env``.

Each variable is written with one request::

    PUT /api/env
    {"key": "QYRAG_BASE_URL", "value": "..."}

Secrets and dataset routing all live in ``~/.hermes/.env`` — same as the
Hermes Web Dashboard API Keys page.

Hermes ``PUT /api/env`` strips non-ASCII from values (Chinese keys become
``""``). After writing ``QYRAG_DATASETS``, Manager rewrites that line in
``/opt/data/.env`` via Docker exec with UTF-8 so ``cat .env`` shows
``{"策略分析": "<id>"}`` instead of ``\\uXXXX`` or an empty key.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.services.hermes_dashboard_service import HermesError, HermesService

if TYPE_CHECKING:
    from app.services.docker_service import DockerService

logger = logging.getLogger(__name__)

# Hermes ~/.hermes/.env keys written via PUT /api/env
ENV_HERMES_ENABLE_PROJECT_PLUGINS = "HERMES_ENABLE_PROJECT_PLUGINS"
ENV_QYRAG_BASE_URL = "QYRAG_BASE_URL"
ENV_QYRAG_API_KEY = "QYRAG_API_KEY"
ENV_QYRAG_DATASETS = "QYRAG_DATASETS"

# Hermes agent plugin id for the QYRAG retrieval plugin bundled in NineClaw.
RAGFLOW_PLUGIN_ID = "NineClaw-QYRAG"

GATEWAY_RESTART_TIMEOUT_SECONDS = 300.0
HERMES_DOTENV_PATH = "/opt/data/.env"


def resolve_ragflow_credentials(
    *,
    base_url: str | None,
    api_key: str | None,
) -> tuple[str, str]:
    """Merge DB config with Manager .env fallbacks."""
    url = (base_url or "").strip() or settings.ragflow_base_url.strip()
    key = (api_key or "").strip() or settings.ragflow_api_key.strip()
    return url, key


def _normalize_dataset_display_name(name: str | None, fallback: str) -> str:
    """Pick a non-empty display name for ``QYRAG_DATASETS`` keys."""
    if isinstance(name, str):
        cleaned = name.strip()
        if cleaned:
            return cleaned
    return fallback.strip() or fallback


def build_rag_deploy_env(
    *,
    base_url: str,
    api_key: str,
    knowledge_ids: list[str],
    knowledge_name_map: dict[str, str] | None = None,
    always_include_datasets: bool = False,
) -> dict[str, str]:
    """Build env vars for ``PUT /api/env`` (one call per key).

    ``QYRAG_DATASETS`` is ``{display_name: dataset_id}``, serialized with
    ``ensure_ascii=False`` so Chinese names stay human-readable in ``.env``
    (e.g. ``{"贸易战": "<id>"}``). Hermes may corrupt CJK via ``PUT /api/env``;
    callers should follow with :func:`rewrite_hermes_dotenv_var_utf8`.

    When ``always_include_datasets`` is True, write ``QYRAG_DATASETS`` even for
    an empty selection (``{}``) so the instance config panel can clear bindings.
    """
    env: dict[str, str] = {
        ENV_HERMES_ENABLE_PROJECT_PLUGINS: "1",
    }
    if base_url:
        env[ENV_QYRAG_BASE_URL] = base_url
    if api_key:
        env[ENV_QYRAG_API_KEY] = api_key
    name_map = knowledge_name_map or {}
    datasets: dict[str, str] = {}
    for knowledge_id in knowledge_ids:
        kid = str(knowledge_id or "").strip()
        if not kid:
            continue
        display = _normalize_dataset_display_name(name_map.get(kid), kid)
        # Keep a stable mapping if two KBs share a display name.
        if display in datasets and datasets[display] != kid:
            display = kid
        datasets[display] = kid
    if datasets or always_include_datasets:
        env[ENV_QYRAG_DATASETS] = json.dumps(datasets, ensure_ascii=False)
    return env


def build_external_knowledge_block(
    *,
    base_url: str,
    api_key: str,
    knowledge_ids: list[str],
) -> dict[str, Any]:
    dataset_ids = [str(kid).strip() for kid in knowledge_ids if str(kid).strip()]
    block: dict[str, Any] = {"dataset_ids": dataset_ids}
    if base_url:
        block["base_url"] = base_url
    if api_key:
        block["api_key"] = api_key
    return block


def build_dotenv_upsert_python(
    key: str, value: str, *, env_path: str = HERMES_DOTENV_PATH
) -> str:
    """Build a ``python3 -c`` script that upserts ``KEY="value"`` as UTF-8."""
    payload = base64.b64encode(
        json.dumps(
            {"key": key, "value": value, "path": env_path},
            ensure_ascii=False,
        ).encode("utf-8")
    ).decode("ascii")
    # Keep the script ASCII-only except via base64 payload.
    return (
        "import base64,json,pathlib\n"
        f"d=json.loads(base64.b64decode('{payload}').decode('utf-8'))\n"
        "key,value,path=d['key'],d['value'],pathlib.Path(d['path'])\n"
        "esc=value.replace('\\\\','\\\\\\\\').replace('\"','\\\\\"')\n"
        "new=f'{key}=\"{esc}\"'\n"
        "lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []\n"
        "out=[];found=False\n"
        "for line in lines:\n"
        "    raw=line[7:] if line.startswith('export ') else line\n"
        "    if raw.startswith(key+'=') or raw.startswith(key+' ='):\n"
        "        out.append(new);found=True\n"
        "    else:\n"
        "        out.append(line)\n"
        "if not found: out.append(new)\n"
        "path.write_text('\\n'.join(out)+('\\n' if out else ''), encoding='utf-8')\n"
        "print('ok', key)\n"
    )


async def rewrite_hermes_dotenv_var_utf8(
    docker_service: DockerService,
    container_id: str,
    key: str,
    value: str,
    *,
    env_path: str = HERMES_DOTENV_PATH,
    timeout: float = 20.0,
    attempts: int = 3,
    retry_delay: float = 1.0,
) -> None:
    """Rewrite one Hermes ``.env`` entry as UTF-8 inside the container.

    Hermes Dashboard ``PUT /api/env`` drops non-ASCII bytes from values. Writing
    the same key/value via container ``python3`` keeps Chinese readable in
    ``cat /opt/data/.env``.

    The Docker-over-SSH bridge drops connections intermittently, so transient
    exec failures are retried a few times before giving up.
    """
    cid = (container_id or "").strip()
    if not cid:
        raise ValueError("container_id is required")
    script = build_dotenv_upsert_python(key, value, env_path=env_path)
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            exit_code, output = await docker_service.exec_container_output(
                cid,
                ["python3", "-c", script],
                timeout=timeout,
            )
            if exit_code not in (0, None):
                raise RuntimeError(
                    f"rewrite {key} in {env_path} failed (exit_code={exit_code}): {output[:500]}"
                )
            logger.info(
                "rewrote hermes dotenv utf-8: container=%s key=%s",
                cid[:12],
                key,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                logger.info(
                    "hermes dotenv utf-8 rewrite attempt %d/%d failed "
                    "(container=%s key=%s): %s — retrying",
                    attempt,
                    attempts,
                    cid[:12],
                    key,
                    exc,
                )
                await asyncio.sleep(retry_delay)
    assert last_error is not None
    raise last_error


async def ensure_ragflow_plugin_enabled(svc: HermesService) -> str:
    """Install (if needed) and enable the bundled QYRAG retrieval agent plugin.

    Install failures are ignored when the plugin is already present; enable
    must succeed for the bundled plugin id.
    """
    try:
        await svc.install_agent_plugin(RAGFLOW_PLUGIN_ID, enable=True)
    except HermesError as exc:
        if exc.status_code >= 500:
            raise
        logger.info(
            "qyrag plugin install skipped for %s: %s",
            RAGFLOW_PLUGIN_ID,
            exc.detail,
        )
    await svc.enable_agent_plugin(RAGFLOW_PLUGIN_ID)
    logger.info("qyrag plugin enabled: %s", RAGFLOW_PLUGIN_ID)
    return RAGFLOW_PLUGIN_ID


async def restart_gateway_and_wait(
    svc: HermesService,
    *,
    timeout: float = GATEWAY_RESTART_TIMEOUT_SECONDS,
) -> None:
    restart_result = await svc.restart_gateway()
    action_name = "gateway-restart"
    if isinstance(restart_result, dict) and restart_result.get("name"):
        action_name = str(restart_result["name"])
    action_status = await svc.wait_action_finished(action_name, timeout=timeout)
    if isinstance(action_status, dict) and action_status.get("exit_code") not in (0, None):
        exit_code = action_status.get("exit_code")
        raise RuntimeError(f"Gateway 重启失败 (exit_code={exit_code})")

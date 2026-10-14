"""Web Sources API Routes.

Routes:
- GET    /web-sources              - List web sources
- POST   /web-sources              - Create a web source
- GET    /web-sources/{id}         - Get a web source
- PUT    /web-sources/{id}         - Update a web source
- DELETE /web-sources/{id}         - Delete a web source
- POST /web-sources/proxy          - Proxy an HTTP request (GET/POST)
- POST /web-sources/run-extractor  - Run user Python code in subprocess sandbox
- POST /web-sources/ai-extractor   - Ask LLM to write extractor code
"""

from __future__ import annotations

import json
import logging
import asyncio
import sys
import textwrap
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import black
import httpx
from aiodocker.exceptions import DockerError
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db.session import async_session_maker, get_session
from app.models.instance import ServiceInstance
from app.models.provider import Provider
from app.models.web_source import WebSource, _utcnow
from app.services.hermes_dashboard_service import HermesError, HermesService
from app.services.instance_service import InstanceService
from app.services.nineclaw_bootstrap import build_dashboard_base_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web-sources", tags=["web-sources"])

TENANT_HEADER = "X-Tenant-ID"


def get_tenant_id(x_tenant_id: str | None = Header(default=None, alias=TENANT_HEADER)) -> str:
    return x_tenant_id or settings.default_tenant_id


# ─── CRUD ─────────────────────────────────────────────────────────────────────


class WebSourceCreate(BaseModel):
    name: str
    description: str = ""
    type: str = "other"
    url: str = ""
    url_base: str = ""


class WebSourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    url: str | None = None
    url_base: str | None = None
    enabled: bool | None = None
    request_config: dict | None = None
    extractor_code: str | None = None
    is_verified: bool | None = None


class WebSourceOut(BaseModel):
    id: str
    name: str
    description: str
    type: str
    url: str
    url_base: str
    enabled: bool
    is_verified: bool
    request_config: dict | None
    extractor_code: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, obj: WebSource) -> "WebSourceOut":
        return cls(
            id=str(obj.id),
            name=obj.name,
            description=obj.description,
            type=obj.type,
            url=obj.url,
            url_base=obj.url_base,
            enabled=obj.enabled,
            is_verified=obj.is_verified,
            request_config=obj.request_config,
            extractor_code=obj.extractor_code,
            created_at=obj.created_at.isoformat(),
            updated_at=obj.updated_at.isoformat(),
        )


class WebSearchDeployRequest(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    instance_ids: list[str] = Field(default_factory=list)


from app.services.websearch_deploy_service import (  # noqa: E402
    WEBSEARCH_PLUGIN_ID,
    build_websearch_deploy_env as _websearch_deploy_env,
    merge_websearch_config as _websearch_deploy_config,
)

async def _get_owned_ws(session: AsyncSession, ws_id: UUID, tenant_id: str) -> WebSource:
    result = await session.execute(
        select(WebSource).where(WebSource.id == ws_id, WebSource.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Web source not found")
    return obj


@router.get("", response_model=list[WebSourceOut])
async def list_web_sources(
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> list[WebSourceOut]:
    result = await session.execute(
        select(WebSource).where(WebSource.tenant_id == tenant_id).order_by(WebSource.created_at.desc())
    )
    return [WebSourceOut.from_orm(r) for r in result.scalars().all()]


@router.post(
    "/deploy",
    summary="流式将 WebSearch 插件配置部署到 NineClaw 实例（SSE，Hermes PUT /api/env）",
)
async def deploy_web_search(
    body: WebSearchDeployRequest,
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> EventSourceResponse:
    source_ids = [s.strip() for s in body.source_ids if s.strip()]
    instance_ids = [i.strip() for i in body.instance_ids if i.strip()]
    if not source_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择一个 Web Search 信源",
        )
    if not instance_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择一个目标实例",
        )

    async with async_session_maker() as session:
        inst_stmt = select(ServiceInstance).where(
            ServiceInstance.tenant_id == tenant_id,
            ServiceInstance.id.in_(instance_ids),
        )
        instances = list((await session.execute(inst_stmt)).scalars().all())
        if len(instances) != len(set(instance_ids)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分实例不存在或不属于当前租户",
            )

    env_vars = _websearch_deploy_env(source_ids)
    inst_by_id = {i.id: i for i in instances}
    ordered_instances = [inst_by_id[iid] for iid in instance_ids if iid in inst_by_id]
    api_key_token = settings.nineclaw_token
    docker_service = request.app.state.docker_service

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        for inst in ordered_instances:
            yield {
                "event": "status",
                "data": json.dumps(
                    {
                        "instance_id": inst.id,
                        "name": inst.name,
                        "status": "pending",
                        "source_id": None,
                        "error": None,
                    },
                    ensure_ascii=False,
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
                        "source_id": None,
                        "error": None,
                    },
                    ensure_ascii=False,
                ),
            }

            actual = (inst.actual_state or "").lower()
            if actual != "running":
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "source_id": None,
                            "error": f"实例当前状态为 {actual or 'unknown'}，必须运行中才能部署",
                        },
                        ensure_ascii=False,
                    ),
                }
                continue

            dash_url = build_dashboard_base_url(inst.id)
            try:
                async with HermesService(base_url=dash_url, api_key=api_key_token) as svc:
                    current_config = await svc.get_config()
                    await svc.put_config(_websearch_deploy_config(current_config))
                    for key, value in env_vars.items():
                        await svc.put_env(key, value)
                    await svc.enable_agent_plugin(WEBSEARCH_PLUGIN_ID)

                async with async_session_maker() as restart_session:
                    restart_svc = InstanceService(
                        session=restart_session,
                        docker_service=docker_service,
                    )
                    await restart_svc.restart_instance(inst.id)
            except HermesError as exc:
                logger.warning(
                    "deploy websearch: hermes error for %s: %s", inst.id, exc.detail
                )
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "source_id": None,
                            "error": f"Hermes {exc.status_code}: {exc.detail}",
                        },
                        ensure_ascii=False,
                    ),
                }
                continue
            except DockerError as exc:
                logger.warning("deploy websearch: container restart failed for %s: %s", inst.id, exc)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "source_id": None,
                            "error": f"容器重启失败: {exc.message}",
                        },
                        ensure_ascii=False,
                    ),
                }
                continue
            except (httpx.RequestError, asyncio.TimeoutError) as exc:
                logger.warning("deploy websearch: connection error for %s: %s", inst.id, exc)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "source_id": None,
                            "error": f"无法连接实例: {exc.__class__.__name__}",
                        },
                        ensure_ascii=False,
                    ),
                }
                continue
            except Exception as exc:
                logger.exception("deploy websearch: unexpected error for %s", inst.id)
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "instance_id": inst.id,
                            "name": inst.name,
                            "status": "failed",
                            "source_id": None,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
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
                        "source_id": None,
                        "error": None,
                    },
                    ensure_ascii=False,
                ),
            }

        yield {
            "event": "done",
            "data": json.dumps({"finished": True}, ensure_ascii=False),
        }

    return EventSourceResponse(event_stream())


@router.post("", response_model=WebSourceOut, status_code=status.HTTP_201_CREATED)
async def create_web_source(
    body: WebSourceCreate,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> WebSourceOut:
    existing_stmt = select(WebSource).where(
        WebSource.tenant_id == tenant_id, WebSource.name == body.name.strip()
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"web 源 '{body.name.strip()}' 已存在",
        )
    obj = WebSource(tenant_id=tenant_id, **body.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return WebSourceOut.from_orm(obj)


@router.get("/{ws_id}", response_model=WebSourceOut)
async def get_web_source(
    ws_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> WebSourceOut:
    return WebSourceOut.from_orm(await _get_owned_ws(session, ws_id, tenant_id))


@router.put("/{ws_id}", response_model=WebSourceOut)
async def update_web_source(
    ws_id: UUID,
    body: WebSourceUpdate,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> WebSourceOut:
    obj = await _get_owned_ws(session, ws_id, tenant_id)
    new_name = body.name.strip() if body.name is not None else None
    if new_name is not None and new_name != obj.name:
        clash_stmt = select(WebSource).where(
            WebSource.tenant_id == tenant_id,
            WebSource.name == new_name,
            WebSource.id != ws_id,
        )
        clash = (await session.execute(clash_stmt)).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"web 源 '{new_name}' 已存在",
            )
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "name" and v is not None:
            setattr(obj, k, v.strip())
        else:
            setattr(obj, k, v)
    obj.updated_at = _utcnow()
    await session.commit()
    await session.refresh(obj)
    return WebSourceOut.from_orm(obj)


@router.delete("/{ws_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_web_source(
    ws_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    obj = await _get_owned_ws(session, ws_id, tenant_id)
    await session.delete(obj)
    await session.commit()


# ─── Search proxy (forwards to nineclaw-sandbox) ─────────────────────────────


@router.get("/{ws_id}/test")
async def test_web_source(ws_id: UUID, query: str) -> dict:
    """Single-source test: proxy to nineclaw-sandbox for debugging."""
    url = f"{settings.nineclaw_sandbox_url}/search"
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.get(url, params={"source_id": str(ws_id), "query": query})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"nineclaw-sandbox 不可达：{exc}") from exc
    return resp.json()


class ProxyRequest(BaseModel):
    method: str = Field("GET", pattern="^(GET|POST)$")
    url: str
    params: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    use_proxy: bool = False
    proxy_url: str = ""


class ProxyResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: str


def _build_client(use_proxy: bool, proxy_url: str) -> httpx.AsyncClient:
    proxies = {"http://": proxy_url, "https://": proxy_url} if use_proxy and proxy_url else None
    return httpx.AsyncClient(proxies=proxies, follow_redirects=True, timeout=30)


@router.post("/proxy", response_model=ProxyResponse)
async def proxy_request(req: ProxyRequest) -> ProxyResponse:
    async with _build_client(req.use_proxy, req.proxy_url) as client:
        try:
            resp = await client.request(
                method=req.method, url=req.url,
                params=req.params or None, headers=req.headers or None,
                content=req.body.encode() if req.body else None,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProxyResponse(status_code=resp.status_code, headers=dict(resp.headers), body=resp.text)


# ─── Format code ──────────────────────────────────────────────────────────────


class FormatCodeRequest(BaseModel):
    code: str


class FormatCodeResponse(BaseModel):
    code: str


@router.post("/format-code", response_model=FormatCodeResponse)
async def format_code(req: FormatCodeRequest) -> FormatCodeResponse:
    try:
        formatted = black.format_str(req.code, mode=black.Mode())
        return FormatCodeResponse(code=formatted)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── Subprocess sandbox ───────────────────────────────────────────────────────

# Wrapper that calls the user's extract(html) and writes JSON result to a file.
# stdout/stderr are free for user's print() statements and will be streamed.
_EXECUTE_PY = textwrap.dedent("""\
import sys, json, resource, os
sys.path.insert(0, "/tmp")
from pydantic import BaseModel
from typing import Optional

# Hard limits: 10 s CPU, 256 MB RAM
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_AS,  (256 * 1024 * 1024, 256 * 1024 * 1024))

html = open(os.environ["_HTML_FILE"], "r").read()
result_file = os.environ["_RESULT_FILE"]


class SearchItem(BaseModel):
    url: str
    title: str
    desc: Optional[str] = None


try:
    from extract import extract
    raw = extract(html)
    if not isinstance(raw, list):
        raise TypeError("extract() must return a list")
    validated = []
    for i, item in enumerate(raw):
        try:
            validated.append(SearchItem.model_validate(item))
        except Exception as ve:
            from pydantic import ValidationError as _VE
            if isinstance(ve, _VE):
                err = ve.errors()[0]
                loc = " -> ".join(str(x) for x in err["loc"])
                actual = type(err["input"]).__name__
                raise TypeError(
                    f"第 {i} 项字段 '{loc}' 校验失败：期望 string，实际传入了 {actual}"
                ) from None
            raise
    with open(result_file, "w") as f:
        json.dump({"result": [i.model_dump() for i in validated]}, f)
except Exception as e:
    import traceback
    traceback.print_exc()
    with open(result_file, "w") as f:
        json.dump({"error": str(e)}, f)
""")


class RunExtractorRequest(BaseModel):
    html: str
    code: str  # user-supplied Python; must define extract(html: str) -> list[dict]


class RunExtractorResponse(BaseModel):
    result: list[dict] | None = None
    error: str | None = None


@router.post("/run-extractor")
async def run_extractor(req: RunExtractorRequest) -> EventSourceResponse:
    from opensandbox.sandbox import Sandbox
    from opensandbox.config import ConnectionConfig
    from opensandbox.models.execd import ExecutionHandlers
    from opensandbox.models.filesystem import WriteEntry
    from opensandbox.exceptions import SandboxException
    from datetime import timedelta

    script = _EXECUTE_PY

    async def stream():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def on_stdout(msg):
            await queue.put({"event": "stdout", "data": json.dumps({"text": msg.text})})

        async def on_stderr(msg):
            await queue.put({"event": "stderr", "data": json.dumps({"text": msg.text})})

        async def run():
            config = ConnectionConfig(
                api_key=settings.open_sandbox_api_key or "no-key",
                domain=settings.open_sandbox_domain,
                protocol=settings.open_sandbox_protocol,
            )
            try:
                sandbox = await Sandbox.create(
                    settings.open_sandbox_image,
                    connection_config=config,
                    timeout=timedelta(seconds=60),
                    env={"_HTML_FILE": "/tmp/response.html", "_RESULT_FILE": "/tmp/result.json"},
                )
                async with sandbox:
                    await sandbox.files.write_files([
                        WriteEntry(path="/tmp/response.html", data=req.html),
                        WriteEntry(path="/tmp/extract.py", data=req.code),
                        WriteEntry(path="/tmp/execute.py", data=script),
                    ])
                    await sandbox.commands.run(
                        "python -u /tmp/execute.py",
                        handlers=ExecutionHandlers(on_stdout=on_stdout, on_stderr=on_stderr),
                    )
                    result_files = await sandbox.files.read_file("/tmp/result.json")
                    result_text = result_files if result_files else None
                    if result_text:
                        data = json.loads(result_text)
                        if data.get("error"):
                            await queue.put({"event": "error", "data": json.dumps({"text": data["error"]})})
                        else:
                            await queue.put({"event": "result", "data": json.dumps({"result": data.get("result", [])})})
                    else:
                        await queue.put({"event": "error", "data": json.dumps({"text": "执行异常：未生成结果文件"})})
                    await sandbox.kill()
            except SandboxException as exc:
                await queue.put({"event": "error", "data": json.dumps({"text": f"Sandbox 错误：{exc.error.message}"})})
            except Exception as exc:
                await queue.put({"event": "error", "data": json.dumps({"text": str(exc)})})
            finally:
                await queue.put(None)

        asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return EventSourceResponse(stream())

    return EventSourceResponse(stream())


# ─── AI extractor ─────────────────────────────────────────────────────────────


class AiExtractorRequest(BaseModel):
    html: str
    provider_id: str
    model: str
    prompt: str = ""


class AiExtractorResponse(BaseModel):
    code: str


_AI_PROMPT = """\
你是一个 Python 爬虫专家。根据下面的 HTML 片段，编写一个 Python 函数：

```python
def extract(html: str) -> list[dict]:
    ...
```

要求：
1. 函数名必须是 `extract`，参数是完整 HTML 字符串
2. 返回值是 list[dict]，每个 dict 必须包含 `url`（str）、`title`（str），可选 `desc`（str）
3. 只使用 Python 标准库（re、html.parser 等），不能 import 第三方库
4. 只输出函数代码，不要任何解释、不要 markdown 代码块标记
{user_instruction}
HTML 片段（前 8000 字符）：
{html}
"""


@router.post("/ai-extractor", response_model=AiExtractorResponse)
async def ai_extractor(
    req: AiExtractorRequest,
    x_tenant_id: str = Header(default="default", alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> AiExtractorResponse:
    # Load provider from DB
    try:
        pid = UUID(req.provider_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 provider_id")

    result = await session.execute(
        select(Provider).where(Provider.id == pid, Provider.tenant_id == x_tenant_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if not provider.api_key:
        raise HTTPException(status_code=400, detail="Provider 未配置 API Key")

    user_instruction = f"\n用户需求：{req.prompt}\n" if req.prompt else ""
    prompt = _AI_PROMPT.format(html=req.html[:8000], user_instruction=user_instruction)

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{provider.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                json={"model": req.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"LLM 请求失败：{exc.response.text[:300]}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    content: str = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if model wrapped the code anyway
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return AiExtractorResponse(code=content)


# ─── Aggregate search (AI-facing, multi-source) ──────────────────────────────


class AggregateSearchResult(BaseModel):
    source_id: str
    source_name: str
    results: list[dict]
    error: str | None = None


class AggregateSearchResponse(BaseModel):
    query: str
    sources: list[AggregateSearchResult]


class AggregateSearchRequest(BaseModel):
    query: str
    include_sources: list[str] | None = None  # source names to include
    exclude_sources: list[str] = []           # source names to exclude


@router.post("/search", response_model=AggregateSearchResponse)
async def aggregate_search(
    body: AggregateSearchRequest,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> AggregateSearchResponse:
    """AI-facing aggregate search. Fans out query to all enabled sources in parallel."""
    from sqlalchemy import select as sa_select
    from app.models.web_source import WebSource

    stmt = sa_select(WebSource).where(
        WebSource.tenant_id == tenant_id,
        WebSource.enabled == True,  # noqa: E712
    )
    rows = (await session.execute(stmt)).scalars().all()

    include = set(body.include_sources) if body.include_sources is not None else None
    exclude = set(body.exclude_sources)
    sources = [
        r for r in rows
        if (include is None or r.name in include)
        and r.name not in exclude
        and r.request_config
        and r.extractor_code
    ]

    sandbox_url = settings.nineclaw_sandbox_url

    async def fetch_one(src: WebSource) -> AggregateSearchResult:
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.get(
                    f"{sandbox_url}/search",
                    params={"source_id": str(src.id), "query": body.query},
                )
                resp.raise_for_status()
                data = resp.json()
                return AggregateSearchResult(
                    source_id=str(src.id),
                    source_name=src.name,
                    results=data.get("results", []),
                )
            except Exception as exc:
                return AggregateSearchResult(
                    source_id=str(src.id),
                    source_name=src.name,
                    results=[],
                    error=str(exc),
                )

    import asyncio as _asyncio
    results = await _asyncio.gather(*[fetch_one(s) for s in sources])
    return AggregateSearchResponse(query=body.query, sources=list(results))


# ─── Agent edit (Kiro-style SSE diff) ────────────────────────────────────────

import asyncio
import difflib
import shutil
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools.coding import CodingTools


class AgentEditRequest(BaseModel):
    code: str           # current extract.py content
    html: str           # response.html content (read-only context)
    instruction: str    # user's natural language request
    provider_id: str
    model: str


@router.post("/agent-edit")
async def agent_edit(
    req: AgentEditRequest,
    x_tenant_id: str = Header(default="default", alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    result = await session.execute(
        select(Provider).where(Provider.id == UUID(req.provider_id), Provider.tenant_id == x_tenant_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    async def stream():
        # Write files to temp dir
        tmp = Path(tempfile.mkdtemp(prefix="nineclaw-ws-"))
        try:
            py_file = tmp / "extract.py"
            html_file = tmp / "response.html"
            py_file.write_text(req.code)
            html_file.write_text(req.html)

            original_code = req.code

            model = OpenAILike(
                id=req.model,
                base_url=provider.base_url,
                api_key=provider.api_key,
            )

            agent = Agent(
                model=model,
                tools=[CodingTools(base_dir=str(tmp))],
                instructions=[
                    "你是一个 Python 代码编辑助手。工作区只有两个文件：",
                    "- extract.py: 需要修改的 Python 提取代码",
                    "- response.html: 只读的 HTML 参考文件",
                    "规则：",
                    "1. 禁止使用 cd 命令，所有操作必须在当前目录进行",
                    "2. 只修改 extract.py，不要修改 response.html",
                    "3. 使用 read_file 读取文件，使用 write_file 或 edit_file 修改 extract.py",
                    "4. 如需验证代码，使用 run_shell 执行 python extract.py，不要加路径前缀",
                    "5. 完成后确保 extract.py 已保存",
                ],
                markdown=False,
                stream=False,
            )

            # Yield thinking event
            yield {"event": "thinking", "data": json.dumps({"text": "正在分析代码..."})}

            # Run agent synchronously in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: agent.run(req.instruction))

            # Read modified file
            new_code = py_file.read_text() if py_file.exists() else original_code

            if new_code == original_code:
                yield {"event": "error", "data": json.dumps({"text": "Agent 未修改文件，请重新描述需求"})}
                return

            # Compute unified diff as hunks
            old_lines = original_code.splitlines(keepends=True)
            new_lines = new_code.splitlines(keepends=True)
            hunks = []
            for group in difflib.SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(3):
                hunk = {"changes": []}
                for tag, i1, i2, j1, j2 in group:
                    if tag == "equal":
                        for line in old_lines[i1:i2]:
                            hunk["changes"].append({"type": "context", "content": line.rstrip("\n")})
                    elif tag in ("replace", "delete"):
                        for line in old_lines[i1:i2]:
                            hunk["changes"].append({"type": "remove", "content": line.rstrip("\n")})
                        if tag == "replace":
                            for line in new_lines[j1:j2]:
                                hunk["changes"].append({"type": "add", "content": line.rstrip("\n")})
                    elif tag == "insert":
                        for line in new_lines[j1:j2]:
                            hunk["changes"].append({"type": "add", "content": line.rstrip("\n")})
                hunks.append(hunk)

            yield {"event": "diff", "data": json.dumps({"new_code": new_code, "hunks": hunks})}
            yield {"event": "done", "data": "{}"}

        except Exception as exc:
            logger.exception("agent_edit error: %s", exc)
            yield {"event": "error", "data": json.dumps({"text": str(exc)})}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return EventSourceResponse(stream())

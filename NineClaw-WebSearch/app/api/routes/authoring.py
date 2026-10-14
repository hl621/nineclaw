"""Source authoring routes: fetch, save_extractor, test."""

from __future__ import annotations

import json
import sys
from difflib import unified_diff
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.source_loader import WEB_SOURCES_DIR

router = APIRouter(prefix="/sources", tags=["authoring"])

def _response_metadata(response: httpx.Response) -> dict:
    """Keep only the response content type needed to choose a parser."""
    return {"content_type": response.headers.get("content-type", "")}


# ── Schemas ───────────────────────────────────────────────────────────────────


class RequestParam(BaseModel):
    key: str
    value: str


class RequestConfig(BaseModel):
    url: str
    method: str = "GET"
    params: list[RequestParam] = []
    headers: list[RequestParam] = []
    body: str = ""
    body_type: str = "application/json"
    proxy_pool: list[str] = []


class FetchRequest(BaseModel):
    source_id: str
    config: RequestConfig
    query: str  # test query, replaces {query} placeholders


class FetchResponse(BaseModel):
    status_code: int
    html: str
    saved: bool


class SaveExtractorRequest(BaseModel):
    source_id: str
    code: str


class EditExtractorRequest(BaseModel):
    source_id: str
    old_text: str
    new_text: str


class EditExtractorResponse(BaseModel):
    source_id: str
    edited: bool
    replacements: int
    diff: str


class TestRequest(BaseModel):
    source_id: str
    query: str


class TestResultItem(BaseModel):
    url: str
    title: str
    desc: str | None = None


class TestResponse(BaseModel):
    success: bool
    results: list[TestResultItem] | None = None
    error: str | None = None
    request_time_ms: int | None = None
    parse_time_ms: int | None = None
    result_count: int | None = None
    status_code: int | None = None


# ── Step 1: /fetch ────────────────────────────────────────────────────────────


@router.post("/fetch", response_model=FetchResponse)
async def fetch(body: FetchRequest):
    """Execute the request config with a test query, save config.json + response.html."""
    cfg = body.config

    def sub(s: str) -> str:
        return s.replace("{query}", body.query)

    params = {p.key: sub(p.value) for p in cfg.params if p.key}
    headers = {h.key: sub(h.value) for h in cfg.headers if h.key}
    url = sub(cfg.url)
    body_str = sub(cfg.body)
    if cfg.method == "POST" and body_str and "Content-Type" not in headers:
        headers["Content-Type"] = cfg.body_type

    proxies = None
    if cfg.proxy_pool:
        import random
        p = random.choice(cfg.proxy_pool)
        proxies = {"http://": p, "https://": p}

    async with httpx.AsyncClient(proxies=proxies, follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.request(
                method=cfg.method,
                url=url,
                params=params or None,
                headers=headers or None,
                content=body_str.encode() if body_str else None,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"请求失败：{exc}") from exc

    # Save to filesystem
    source_dir = WEB_SOURCES_DIR / body.source_id
    if not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="Source not found, create card first via POST /sources")

    # Update config.json: merge request config into existing card
    config_path = source_dir / "config.json"
    existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    existing["request"] = cfg.model_dump()
    existing["response"] = _response_metadata(resp)
    config_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save response.html
    (source_dir / "response.html").write_text(resp.text, encoding="utf-8")

    return FetchResponse(status_code=resp.status_code, html=resp.text, saved=True)


# ── Step 2: /save_extractor ──────────────────────────────────────────────────


@router.post("/save_extractor")
async def save_extractor(body: SaveExtractorRequest):
    """Save extract.py code to the source directory."""
    source_dir = WEB_SOURCES_DIR / body.source_id
    if not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="Source directory not found, run /fetch first")

    # Validate syntax
    try:
        compile(body.code, "extract.py", "exec")
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"语法错误：{exc}") from exc

    (source_dir / "extract.py").write_text(body.code, encoding="utf-8")
    return {"source_id": body.source_id, "saved": True}


@router.post("/edit_extractor", response_model=EditExtractorResponse)
async def edit_extractor(body: EditExtractorRequest):
    """Replace one uniquely matching code fragment in the saved extract.py."""
    source_dir = WEB_SOURCES_DIR / body.source_id
    extract_path = source_dir / "extract.py"
    if not source_dir.is_dir() or not extract_path.is_file():
        raise HTTPException(status_code=404, detail="extract.py not found")
    if not body.old_text:
        raise HTTPException(status_code=400, detail="old_text cannot be empty")
    if body.old_text == body.new_text:
        raise HTTPException(
            status_code=400,
            detail="old_text and new_text are identical",
        )

    current_code = extract_path.read_text(encoding="utf-8")
    match_count = current_code.count(body.old_text)
    if match_count == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "old_text was not found in extract.py; read the latest code and "
                "match whitespace and indentation exactly"
            ),
        )
    if match_count > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"old_text matched {match_count} locations in extract.py; "
                "include more surrounding code so it matches exactly once"
            ),
        )

    updated_code = current_code.replace(body.old_text, body.new_text, 1)
    try:
        compile(updated_code, "extract.py", "exec")
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"语法错误：{exc}") from exc

    diff = "\n".join(
        unified_diff(
            current_code.splitlines(),
            updated_code.splitlines(),
            fromfile="a/extract.py",
            tofile="b/extract.py",
            lineterm="",
        )
    )
    extract_path.write_text(updated_code, encoding="utf-8")
    return EditExtractorResponse(
        source_id=body.source_id,
        edited=True,
        replacements=1,
        diff=diff,
    )


# ── Step 3: /test ─────────────────────────────────────────────────────────────


@router.post("/test", response_model=TestResponse)
async def test_source(body: TestRequest):
    """Execute full search flow: fetch with query + run extract.py, return results."""
    import time
    from app.services.source_loader import get_source as load_source

    t0 = time.perf_counter()

    source = load_source(body.source_id)
    if source is None:
        return TestResponse(success=False, error="Source not found")

    cfg = source.request_config
    if not cfg.get("url"):
        return TestResponse(success=False, error="No request URL configured, run /fetch first")

    # Fetch
    def sub(s: str) -> str:
        return s.replace("{query}", body.query)

    params = {p["key"]: sub(p["value"]) for p in cfg.get("params", []) if p.get("key")}
    headers = {h["key"]: sub(h["value"]) for h in cfg.get("headers", []) if h.get("key")}
    url = sub(cfg["url"])
    body_str = sub(cfg.get("body", ""))
    if cfg.get("method") == "POST" and body_str and "Content-Type" not in headers:
        headers["Content-Type"] = cfg.get("body_type", "application/json")

    proxies = None
    if cfg.get("proxy_pool"):
        import random
        p = random.choice(cfg["proxy_pool"])
        proxies = {"http://": p, "https://": p}
    elif cfg.get("use_proxy") and cfg.get("proxy_url"):
        proxies = {"http://": cfg["proxy_url"], "https://": cfg["proxy_url"]}

    http_status = None
    async with httpx.AsyncClient(proxies=proxies, follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.request(
                method=cfg.get("method", "GET"),
                url=url,
                params=params or None,
                headers=headers or None,
                content=body_str.encode() if body_str else None,
            )
            http_status = resp.status_code
        except httpx.RequestError as exc:
            return TestResponse(success=False, error=f"请求失败：{exc}", request_time_ms=int((time.perf_counter() - t0) * 1000))

    req_ms = int((time.perf_counter() - t0) * 1000)

    # Extract
    t1 = time.perf_counter()
    try:
        extract_fn = source.extract_fn
    except (SyntaxError, KeyError) as exc:
        return TestResponse(success=False, error=f"extract.py 加载失败：{exc}", request_time_ms=req_ms, parse_time_ms=int((time.perf_counter() - t1) * 1000), status_code=http_status)

    try:
        raw = extract_fn(resp.text)
    except Exception as exc:
        return TestResponse(success=False, error=f"extract() 执行出错：{exc}", request_time_ms=req_ms, parse_time_ms=int((time.perf_counter() - t1) * 1000), status_code=http_status)

    if not isinstance(raw, list):
        return TestResponse(success=False, error="extract() 必须返回 list", request_time_ms=req_ms, parse_time_ms=int((time.perf_counter() - t1) * 1000), status_code=http_status)

    # Resolve relative URLs
    from urllib.parse import urljoin
    base = source.url_base or url
    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_url = str(item.get("url", ""))
        if item_url and not item_url.startswith("http"):
            item_url = urljoin(base, item_url)
        results.append(TestResultItem(
            url=item_url,
            title=str(item.get("title", "")),
            desc=str(item["desc"]) if item.get("desc") else None,
        ))
    parse_ms = int((time.perf_counter() - t1) * 1000)

    return TestResponse(success=True, results=results, request_time_ms=req_ms, parse_time_ms=parse_ms, result_count=len(results), status_code=http_status)


# ── Debug extractor (SSE) ─────────────────────────────────────────────────────


class DebugExtractorRequest(BaseModel):
    source_id: str


class RunExtractorResponse(BaseModel):
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    result: dict | None = None
    time_ms: int


_RUNNER_SCRIPT = '''\
import sys, json, traceback

html_path = sys.argv[1]
code_path = sys.argv[2]

html = open(html_path, "r", encoding="utf-8").read()
code = open(code_path, "r", encoding="utf-8").read()

ns = {}
try:
    exec(compile(code, "extract.py", "exec"), ns)
except Exception:
    traceback.print_exc()
    sys.exit(1)

extract_fn = ns.get("extract")
if not callable(extract_fn):
    print("ERROR: extract.py 中未找到 extract 函数", file=sys.stderr)
    sys.exit(1)

try:
    raw = extract_fn(html)
except Exception:
    traceback.print_exc()
    sys.exit(1)

if not isinstance(raw, list):
    print("ERROR: extract() 必须返回 list，实际返回了 " + type(raw).__name__, file=sys.stderr)
    sys.exit(1)

# Validate each item format
for i, item in enumerate(raw):
    if not isinstance(item, dict):
        print(f"返回结果第 {i} 项内容:\\n{repr(item)[:500]}", file=sys.stderr)
        print(f"ERROR: 返回结果中检测到第 {i} 项必须是 dict，实际是 {type(item).__name__}", file=sys.stderr)
        sys.exit(1)
    for key in ("url", "title"):
        if key not in item:
            print(f"返回结果第 {i} 项内容:\\n{json.dumps(item, ensure_ascii=False, indent=2, default=repr)}", file=sys.stderr)
            print(f"ERROR: 返回结果中检测到第 {i} 项缺少必填字段 '{key}'，当前 keys: {list(item.keys())}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(item[key], str):
            print(f"返回结果第 {i} 项内容:\\n{json.dumps(item, ensure_ascii=False, indent=2, default=repr)}", file=sys.stderr)
            print(f"ERROR: 返回结果中检测到第 {i} 项字段 '{key}' 必须是 str，实际是 {type(item[key]).__name__}", file=sys.stderr)
            sys.exit(1)
    if "desc" in item and item["desc"] is not None and not isinstance(item["desc"], str):
        print(f"返回结果第 {i} 项内容:\\n{json.dumps(item, ensure_ascii=False, indent=2, default=repr)}", file=sys.stderr)
        print(f"ERROR: 返回结果中检测到第 {i} 项字段 'desc' 必须是 str 或 None，实际是 {type(item['desc']).__name__}", file=sys.stderr)
        sys.exit(1)

# Output result as special marker line
print("\\n__RESULT__" + json.dumps({"count": len(raw), "items": raw[:50]}, ensure_ascii=False))
'''


@router.post("/debug_extractor")
async def debug_extractor(body: DebugExtractorRequest):
    """Run saved extract.py against local response.html via subprocess with real-time SSE streaming."""
    import asyncio
    import tempfile
    from sse_starlette.sse import EventSourceResponse

    source_dir = WEB_SOURCES_DIR / body.source_id
    response_path = source_dir / "response.html"
    extract_path = source_dir / "extract.py"

    if not response_path.exists():
        raise HTTPException(status_code=404, detail="response.html not found")
    if not extract_path.exists():
        raise HTTPException(status_code=404, detail="extract.py not found")

    async def stream():
        import time as _time
        t0 = _time.perf_counter()
        tmp_runner = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
        tmp_runner.write(_RUNNER_SCRIPT)
        tmp_runner.close()

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", tmp_runner.name, str(response_path), str(extract_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_stream(pipe, event_name):
                async for line in pipe:
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    if text.startswith("__RESULT__"):
                        yield {"event": "result", "data": text[len("__RESULT__"):]}
                    else:
                        yield {"event": event_name, "data": json.dumps({"text": text})}

            # Read stdout and stderr concurrently
            stdout_lines = read_stream(proc.stdout, "stdout")
            stderr_lines = read_stream(proc.stderr, "stderr")

            # Interleave both streams
            async def merged():
                import asyncio as _aio
                stdout_done = False
                stderr_done = False
                stdout_iter = stdout_lines.__aiter__()
                stderr_iter = stderr_lines.__aiter__()

                async def next_or_none(it):
                    try:
                        return await it.__anext__()
                    except StopAsyncIteration:
                        return None

                while not stdout_done or not stderr_done:
                    tasks = {}
                    if not stdout_done:
                        tasks["out"] = _aio.ensure_future(next_or_none(stdout_iter))
                    if not stderr_done:
                        tasks["err"] = _aio.ensure_future(next_or_none(stderr_iter))

                    done, _ = await _aio.wait(tasks.values(), return_when=_aio.FIRST_COMPLETED)
                    for t in done:
                        result = t.result()
                        if t == tasks.get("out"):
                            if result is None:
                                stdout_done = True
                            else:
                                yield result
                        elif t == tasks.get("err"):
                            if result is None:
                                stderr_done = True
                            else:
                                yield result
                    # Cancel pending
                    for key, t in tasks.items():
                        if t not in done:
                            t.cancel()

            async for event in merged():
                yield event

            await proc.wait()
            if proc.returncode != 0:
                yield {"event": "exit", "data": json.dumps({"code": proc.returncode})}

        finally:
            import os
            os.unlink(tmp_runner.name)

        yield {"event": "done", "data": json.dumps({"time_ms": int((_time.perf_counter() - t0) * 1000)})}

    return EventSourceResponse(stream())


@router.post("/run_extractor", response_model=RunExtractorResponse)
async def run_extractor(body: DebugExtractorRequest):
    """Run extract.py against saved HTML and return complete logs as JSON."""
    import asyncio
    import os
    import tempfile
    import time

    source_dir = WEB_SOURCES_DIR / body.source_id
    response_path = source_dir / "response.html"
    extract_path = source_dir / "extract.py"

    if not response_path.exists():
        raise HTTPException(status_code=404, detail="response.html not found")
    if not extract_path.exists():
        raise HTTPException(status_code=404, detail="extract.py not found")

    started_at = time.perf_counter()
    tmp_runner = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    )
    tmp_runner.write(_RUNNER_SCRIPT)
    tmp_runner.close()

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            tmp_runner.name,
            str(response_path),
            str(extract_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
    finally:
        os.unlink(tmp_runner.name)

    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace").rstrip("\n")
    stdout_lines: list[str] = []
    result: dict | None = None
    for line in raw_stdout.splitlines():
        if line.startswith("__RESULT__"):
            try:
                parsed = json.loads(line[len("__RESULT__") :])
            except json.JSONDecodeError:
                stdout_lines.append(line)
            else:
                if isinstance(parsed, dict):
                    result = parsed
                else:
                    stdout_lines.append(line)
        else:
            stdout_lines.append(line)

    return RunExtractorResponse(
        success=proc.returncode == 0 and result is not None,
        exit_code=proc.returncode or 0,
        stdout="\n".join(stdout_lines).strip("\n"),
        stderr=stderr,
        result=result,
        time_ms=int((time.perf_counter() - started_at) * 1000),
    )

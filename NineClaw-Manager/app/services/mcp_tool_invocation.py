"""MCP tool invocation service — calls a tool on an MCP server and returns results."""

import asyncio
import logging
import tempfile
import time
from typing import Any

from app.services.mcp_common import format_error, read_errlog

logger = logging.getLogger(__name__)

TOOL_CALL_TIMEOUT = 60.0  # seconds
TOOL_CALL_CONCURRENCY = 5  # max concurrent tool calls
_call_semaphore = asyncio.Semaphore(TOOL_CALL_CONCURRENCY)


def _serialize_content_item(item: Any) -> dict:
    """Convert an MCP SDK content object to a plain dict."""
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    if isinstance(item, dict):
        return item
    return {"type": "text", "text": str(item)}


async def _call_tool_on_session(
    session: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[list[dict], bool]:
    """Run initialize + call_tool on an existing ClientSession, return (content, is_error)."""
    await session.initialize()
    result = await session.call_tool(tool_name, arguments)
    content = [_serialize_content_item(c) for c in (result.content or [])]
    return content, bool(getattr(result, "isError", False))


async def call_tool(
    transport: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[list[dict], bool, float]:
    """Call a tool on an MCP server.

    For stdio: kwargs must include ``command``, ``args``, optionally ``env``
    For url:   kwargs must include ``url``, optionally ``headers``

    Returns (content, is_error, duration_ms).
    """
    arguments = arguments or {}
    async with _call_semaphore:
        start = time.monotonic()
        try:
            if transport == "stdio":
                return await _call_stdio(tool_name, arguments, **kwargs)
            elif transport == "url":
                return await _call_url(tool_name, arguments, **kwargs)
            else:
                elapsed = (time.monotonic() - start) * 1000
                return (
                    [{"type": "text", "text": f"Unsupported transport: {transport}"}],
                    True,
                    elapsed,
                )
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return (
                [{"type": "text", "text": "工具调用超时（60 秒），请检查 MCP 服务器是否正常响应"}],
                True,
                elapsed,
            )
        except Exception as e:
            logger.exception("Tool call '%s' failed unexpectedly", tool_name)
            elapsed = (time.monotonic() - start) * 1000
            return (
                [{"type": "text", "text": format_error(e)}],
                True,
                elapsed,
            )


async def _call_stdio(
    tool_name: str,
    arguments: dict[str, Any],
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    **_,
) -> tuple[list[dict], bool, float]:
    """Call a tool via stdio transport."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=command,
        args=args or [],
        env=env or None,
    )

    errlog_file = tempfile.TemporaryFile(mode="w+", suffix=".log")
    start = time.monotonic()
    try:
        async with asyncio.timeout(TOOL_CALL_TIMEOUT):
            async with stdio_client(server_params, errlog=errlog_file) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    content, is_error = await _call_tool_on_session(
                        session, tool_name, arguments
                    )
                    elapsed = (time.monotonic() - start) * 1000
                    return content, is_error, elapsed
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        stderr_text = read_errlog(errlog_file)
        msg = format_error(None, stderr_text, command)
        if not stderr_text:
            msg = f"工具调用超时，请检查 '{command}' 命令是否正确且可正常运行"
        return [{"type": "text", "text": msg}], True, elapsed
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        stderr_text = read_errlog(errlog_file)
        error_msg = format_error(e, stderr_text, command)
        logger.warning("Stdio tool call '%s' on '%s' failed: %s", tool_name, command, error_msg)
        return [{"type": "text", "text": error_msg}], True, elapsed
    finally:
        errlog_file.close()


async def _call_url(
    tool_name: str,
    arguments: dict[str, Any],
    url: str,
    headers: dict[str, str] | None = None,
    **_,
) -> tuple[list[dict], bool, float]:
    """Call a tool via URL transport.

    Tries Streamable HTTP first; falls back to the legacy SSE transport when the
    server speaks SSE (e.g. URLs containing ``/sse``).
    """
    import httpx
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client

    http_client = None
    if headers:
        http_client = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(TOOL_CALL_TIMEOUT, read=300.0),
        )

    start = time.monotonic()
    try:
        # Streamable HTTP first.
        try:
            async with asyncio.timeout(TOOL_CALL_TIMEOUT):
                async with streamable_http_client(url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        content, is_error = await _call_tool_on_session(
                            session, tool_name, arguments
                        )
                        elapsed = (time.monotonic() - start) * 1000
                        return content, is_error, elapsed
        except asyncio.TimeoutError:
            raise
        except Exception as streamable_err:
            logger.debug(
                "Streamable HTTP tool call '%s' on '%s' failed, retrying with SSE: %s",
                tool_name,
                url,
                streamable_err,
            )

        # SSE fallback.
        async with asyncio.timeout(TOOL_CALL_TIMEOUT):
            async with sse_client(
                url,
                headers=headers or None,
                timeout=TOOL_CALL_TIMEOUT,
                sse_read_timeout=300.0,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    content, is_error = await _call_tool_on_session(
                        session, tool_name, arguments
                    )
                    elapsed = (time.monotonic() - start) * 1000
                    return content, is_error, elapsed
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return (
            [{"type": "text", "text": f"工具调用超时（{TOOL_CALL_TIMEOUT:.0f} 秒），请检查 MCP 服务器是否可达"}],
            True,
            elapsed,
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        error_msg = format_error(e)
        logger.warning("URL tool call '%s' on '%s' failed: %s", tool_name, url, error_msg)
        return [{"type": "text", "text": error_msg}], True, elapsed
    finally:
        if http_client is not None:
            await http_client.aclose()

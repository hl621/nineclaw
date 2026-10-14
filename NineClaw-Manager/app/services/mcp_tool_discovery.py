"""MCP tool discovery service — connects to MCP servers to list their tools."""

import asyncio
import logging
import tempfile
from typing import Any

from app.services.mcp_common import format_error, read_errlog

logger = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 30.0  # seconds


async def discover_tools(
    transport: str, **kwargs
) -> tuple[list[dict[str, Any]], str | None]:
    """Discover tools from an MCP server.

    For stdio: kwargs must include ``command``, ``args``, optionally ``env``
    For url: kwargs must include ``url``, optionally ``headers``

    Returns (tools_list, error_message). On success error_message is None.
    tools_list items: {"name": str, "description": str, "inputSchema": dict}
    """
    try:
        if transport == "stdio":
            return await _discover_stdio(**kwargs)
        elif transport == "url":
            return await _discover_url(**kwargs)
        else:
            return [], f"Unsupported transport: {transport}"
    except asyncio.TimeoutError:
        return [], "工具发现超时，请检查 MCP 服务器命令是否正确且可正常运行"
    except Exception as e:
        logger.exception("Tool discovery failed")
        return [], format_error(e)


async def _discover_stdio(
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    **_,
) -> tuple[list[dict], str | None]:
    """Discover tools via stdio transport."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=command,
        args=args or [],
        env=env or None,
    )

    # Capture subprocess stderr to a temp file for better error reporting.
    # errlog must be a real TextIO with a file descriptor (Popen requirement).
    errlog_file = tempfile.TemporaryFile(mode="w+", suffix=".log")
    try:
        async with asyncio.timeout(DISCOVERY_TIMEOUT):
            async with stdio_client(server_params, errlog=errlog_file) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = []
                    for tool in result.tools:
                        tools.append(
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "inputSchema": tool.inputSchema
                                if hasattr(tool, "inputSchema")
                                else {},
                            }
                        )
                    return tools, None
    except asyncio.TimeoutError:
        stderr_text = read_errlog(errlog_file)
        msg = format_error(None, stderr_text, command)
        if not stderr_text:
            msg = f"工具发现超时，请检查 '{command}' 命令是否正确且可正常运行"
        return [], msg
    except Exception as e:
        stderr_text = read_errlog(errlog_file)
        error_msg = format_error(e, stderr_text, command)
        logger.warning("Stdio discovery for '%s' failed: %s", command, error_msg)
        return [], error_msg
    finally:
        errlog_file.close()


async def _discover_url(
    url: str,
    headers: dict[str, str] | None = None,
    **_,
) -> tuple[list[dict], str | None]:
    """Discover tools via URL transport.

    Tries the Streamable HTTP transport first; falls back to the legacy SSE
    transport when the server speaks SSE instead (e.g. URLs containing ``/sse``).
    """
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client

    import httpx

    # Build custom httpx client with headers if provided, matching SDK defaults
    http_client = None
    if headers:
        http_client = httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(DISCOVERY_TIMEOUT, read=300.0),
        )

    async def _list_tools(read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                    if hasattr(tool, "inputSchema")
                    else {},
                }
                for tool in result.tools
            ]

    try:
        # Streamable HTTP (2025-03-26 spec) — the modern default.
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT):
                async with streamable_http_client(url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    return await _list_tools(read_stream, write_stream), None
        except Exception as streamable_err:
            # SSE transport (2024-11-05 spec) — still common for third-party
            # servers whose URL contains /sse. Only retry if the failure looks
            # like a protocol/handshake mismatch, not a genuine timeout.
            if isinstance(streamable_err, asyncio.TimeoutError):
                raise
            logger.debug(
                "Streamable HTTP discovery failed for %s, retrying with SSE: %s",
                url,
                streamable_err,
            )

        # SSE fallback. sse_client manages its own httpx client, so pass headers
        # through directly rather than reusing the custom http_client.
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT):
                async with sse_client(
                    url,
                    headers=headers or None,
                    timeout=DISCOVERY_TIMEOUT,
                    sse_read_timeout=300.0,
                ) as (read_stream, write_stream):
                    return await _list_tools(read_stream, write_stream), None
        except asyncio.TimeoutError:
            return [], "工具发现超时，请检查 MCP 服务器 URL 是否正确且可正常运行"
        except Exception as e:
            logger.warning("SSE discovery for '%s' failed: %s", url, e)
            return [], format_error(e)
    finally:
        if http_client is not None:
            await http_client.aclose()

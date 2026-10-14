"""Shared utilities for MCP tool discovery and invocation services."""

from typing import IO


def unwrap_exception(exc: BaseException) -> BaseException:
    """Extract the root cause from ExceptionGroup chains."""
    seen: set[int] = set()
    while isinstance(exc, (ExceptionGroup, BaseExceptionGroup)):  # noqa: F821
        if id(exc) in seen or not exc.exceptions:
            break
        seen.add(id(exc))
        exc = exc.exceptions[0]
    return exc


_USELESS_ROOT_MESSAGES = {
    "unhandled errors in a TaskGroup",
    "Connection closed",
}


def format_error(
    exc: BaseException | None,
    stderr_text: str = "",
    command: str = "",
) -> str:
    """Build a user-friendly error message from exception + captured stderr.

    Stderr from the MCP server process is the most useful source — it often
    contains the actual reason the process exited (e.g. missing env vars,
    invalid config).  We always surface stderr content; generic exception
    wrappers like ``Connection closed`` or ``ExceptionGroup`` are suppressed.
    """
    parts: list[str] = []

    # 1. Stderr lines from the subprocess — most valuable
    if stderr_text:
        seen: set[str] = set()
        for line in stderr_text.strip().splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            parts.append(line)
            if len(parts) >= 3:
                break

    # 2. Root exception — only if not a generic wrapper
    if exc is not None and not parts:
        root = unwrap_exception(exc)
        root_msg = str(root).strip()
        if root_msg and root_msg not in _USELESS_ROOT_MESSAGES:
            parts.append(root_msg)

    # 3. Fallback
    if not parts:
        label = f"'{command}'" if command else "MCP server"
        parts.append(f"{label} 进程异常退出，请检查命令配置是否正确")

    return "; ".join(parts)


def read_errlog(f: IO[str]) -> str:
    """Safely read captured stderr from the temp file."""
    try:
        f.seek(0)
        return f.read()
    except Exception:
        return ""

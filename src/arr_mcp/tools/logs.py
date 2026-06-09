"""Log reading and searching tools."""

from __future__ import annotations

import collections
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings

# File types blocked via log tools when the path is outside /var/log.
# This prevents log_read from being used to read config.xml or SQLite
# files that happen to sit alongside log files in services_dir.
_LOG_BLOCKED_NAMES = {"config.xml"}
_LOG_BLOCKED_SUFFIXES = {".db", ".db-shm", ".db-wal"}

_VARLOG = Path("/var/log")


def _check_log_path(path: str, extra_roots: list[Path] | None = None) -> Path:
    try:
        p = Path(path).resolve()
    except ValueError as exc:
        raise PermissionError(f"Invalid path: {exc}") from exc
    allowed = [_VARLOG]
    if extra_roots:
        allowed.extend(extra_roots)
    if not any(str(p).startswith(str(a)) for a in allowed):
        raise PermissionError(f"Log path not allowed: {p}")
    # Outside /var/log, block sensitive file names and extensions.
    if not str(p).startswith(str(_VARLOG)):
        if p.name in _LOG_BLOCKED_NAMES or p.suffix in _LOG_BLOCKED_SUFFIXES:
            raise PermissionError(f"Access to this file is blocked via log tools: {p.name}")
    return p


def register_log_tools(server: FastMCP, settings: Settings) -> None:
    """Register log reading and searching tools with the MCP server."""
    extra_roots = [
        Path(settings.compose_dir).resolve(),
        Path(settings.services_dir).resolve(),
    ]

    @server.tool()
    async def log_read(path: str, lines: int = 100) -> list[TextContent]:
        """Read the last N lines of a log file."""
        p = _check_log_path(path, extra_roots)
        if not p.exists():
            return [TextContent(type="text", text=f"File not found: {p}")]
        tail: collections.deque[str] = collections.deque(maxlen=lines)
        with p.open(errors="replace") as f:
            for line in f:
                tail.append(line)
        return [TextContent(type="text", text="".join(tail) or "(empty)")]

    @server.tool()
    async def log_search(path: str, query: str, lines: int = 50) -> list[TextContent]:
        """Search a log file for lines matching a query string (case-insensitive)."""
        p = _check_log_path(path, extra_roots)
        if not p.exists():
            return [TextContent(type="text", text=f"File not found: {p}")]
        q = query.lower()
        matches: list[str] = []
        with p.open(errors="replace") as f:
            for line in f:
                if q in line.lower():
                    matches.append(line)
        matches = matches[-lines:]
        header = f"Last {len(matches)} matches for '{query}' in {p}:\n"
        return [TextContent(type="text", text=header + "".join(matches) or "(no matches)")]

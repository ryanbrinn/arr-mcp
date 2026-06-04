"""Log reading and searching tools."""

from __future__ import annotations

import collections
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings


def _check_log_path(path: str, extra_roots: list[Path] | None = None) -> Path:
    try:
        p = Path(path).resolve()
    except ValueError as exc:
        raise PermissionError(f"Invalid path: {exc}") from exc
    allowed = [Path("/var/log")]
    if extra_roots:
        allowed.extend(extra_roots)
    if not any(str(p).startswith(str(a)) for a in allowed):
        raise PermissionError(f"Log path not allowed: {p}")
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

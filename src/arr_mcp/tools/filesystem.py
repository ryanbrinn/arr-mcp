"""Filesystem tools."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings

# Paths that may be read/written
_ALLOWED_ROOTS = ["/opt/stacks", "/media-server", "/var/log"]


def _check_path(path: str, settings: Settings) -> Path:
    p = Path(path).resolve()
    allowed = [
        Path(settings.stacks_dir).resolve(),
        Path(settings.media_dir).resolve(),
        Path("/var/log").resolve(),
    ]
    if not any(str(p).startswith(str(a)) for a in allowed):
        raise PermissionError(f"Path not in allowed roots: {p}")
    return p


def register_filesystem_tools(server: FastMCP, settings: Settings) -> None:

    @server.tool()
    async def disk_usage(path: str = "/media-server"):
        """Show disk usage for a path."""
        p = _check_path(path, settings)
        total, used, free = shutil.disk_usage(str(p))
        return [TextContent(
            type="text",
            text=(
                f"Path:  {p}\n"
                f"Total: {total / 1e9:.1f} GB\n"
                f"Used:  {used / 1e9:.1f} GB ({used / total * 100:.1f}%)\n"
                f"Free:  {free / 1e9:.1f} GB"
            ),
        )]

    @server.tool()
    async def directory_list(path: str):
        """List files and directories at a path."""
        p = _check_path(path, settings)
        if not p.exists():
            return [TextContent(type="text", text=f"Path not found: {p}")]
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = []
        for e in entries:
            kind = "DIR " if e.is_dir() else "FILE"
            size = f"{e.stat().st_size:>12,}" if e.is_file() else ""
            lines.append(f"{kind}  {size}  {e.name}")
        return [TextContent(type="text", text="\n".join(lines) or "(empty)")]

    @server.tool()
    async def file_read(path: str):
        """Read a text file."""
        p = _check_path(path, settings)
        return [TextContent(type="text", text=p.read_text(errors="replace"))]

    @server.tool()
    async def file_write(path: str, content: str):
        """Write content to a file (creates parent dirs as needed)."""
        p = _check_path(path, settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return [TextContent(type="text", text=f"Written: {p} ({len(content)} bytes)")]

"""Filesystem tools."""

from __future__ import annotations

import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tools.utils import is_owned_by_current_user

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
    """Register filesystem read/write tools with the MCP server."""

    @server.tool()
    async def disk_usage(path: str = "/media-server") -> list[TextContent]:
        """Show disk usage for a path."""
        p = _check_path(path, settings)
        total, used, free = shutil.disk_usage(str(p))
        return [
            TextContent(
                type="text",
                text=(
                    f"Path:  {p}\n"
                    f"Total: {total / 1e9:.1f} GB\n"
                    f"Used:  {used / 1e9:.1f} GB ({used / total * 100:.1f}%)\n"
                    f"Free:  {free / 1e9:.1f} GB"
                ),
            )
        ]

    @server.tool()
    async def directory_list(path: str) -> list[TextContent]:
        """List files and directories at a path."""
        p = _check_path(path, settings)
        if not p.exists():
            return [TextContent(type="text", text=f"Path not found: {p}")]
        stacks_root = Path(settings.stacks_dir).resolve()
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = []
        for e in entries:
            # Hide directories not owned by the current user when inside stacks_dir
            if e.is_dir() and p == stacks_root and not is_owned_by_current_user(e):
                continue
            kind = "DIR " if e.is_dir() else "FILE"
            size = f"{e.stat().st_size:>12,}" if e.is_file() else ""
            lines.append(f"{kind}  {size}  {e.name}")
        return [TextContent(type="text", text="\n".join(lines) or "(empty)")]

    @server.tool()
    async def file_read(path: str) -> list[TextContent]:
        """Read a text file."""
        p = _check_path(path, settings)
        return [TextContent(type="text", text=p.read_text(errors="replace"))]

    @server.tool()
    async def file_write(path: str, content: str) -> list[TextContent]:
        """Write content to a file (creates parent dirs as needed)."""
        p = _check_path(path, settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return [TextContent(type="text", text=f"Written: {p} ({len(content)} bytes)")]

    @server.tool()
    async def file_delete(path: str, confirm: bool = False) -> list[TextContent]:
        """Delete a file. Requires confirm=True to prevent accidental deletion."""
        if not confirm:
            return [
                TextContent(
                    type="text",
                    text=f"Pass confirm=True to delete {path}.",
                )
            ]
        p = _check_path(path, settings)
        if not p.exists():
            return [TextContent(type="text", text=f"File not found: {p}")]
        if p.is_dir():
            return [
                TextContent(
                    type="text",
                    text="Path is a directory — use a more specific tool.",
                )
            ]
        if not is_owned_by_current_user(p):
            raise PermissionError(f"Cannot delete file not owned by current user: {p}")
        p.unlink()
        return [TextContent(type="text", text=f"Deleted: {p}")]

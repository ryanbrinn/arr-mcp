"""Filesystem tools."""

from __future__ import annotations

import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tools.utils import is_owned_by_current_user

# Filename patterns blocked from read access within services_dir
_SERVICES_BLOCKLIST = {"config.xml"}
_SERVICES_BLOCKED_SUFFIXES = {".db", ".db-shm", ".db-wal"}


def _is_services_blocked(p: Path) -> bool:
    return p.name in _SERVICES_BLOCKLIST or p.suffix in _SERVICES_BLOCKED_SUFFIXES


def _check_path(path: str, settings: Settings, *, write: bool = False) -> Path:
    try:
        p = Path(path).resolve()
    except ValueError as exc:
        raise PermissionError(f"Invalid path: {exc}") from exc

    services_root = Path(settings.services_dir).resolve()
    stacks_root = Path(settings.stacks_dir).resolve()
    media_root = Path(settings.media_dir).resolve()

    in_services = str(p).startswith(str(services_root))
    in_stacks = str(p).startswith(str(stacks_root))
    in_media = str(p).startswith(str(media_root))

    if not (in_services or in_stacks or in_media):
        raise PermissionError(f"Path not in allowed roots: {p}")

    if in_services:
        if write:
            raise PermissionError(f"Write access is not permitted in services_dir: {p}")
        if _is_services_blocked(p):
            raise PermissionError(f"Access to this file is blocked: {p.name}")

    return p


def register_filesystem_tools(server: FastMCP, settings: Settings) -> None:
    """Register filesystem read/write tools with the MCP server."""

    @server.tool()
    async def disk_usage(path: str = settings.media_dir) -> list[TextContent]:
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
        p = _check_path(path, settings, write=True)
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
        p = _check_path(path, settings, write=True)
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

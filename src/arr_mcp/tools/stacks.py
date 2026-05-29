"""Stack management tools (podman-compose)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient

log = logging.getLogger(__name__)


async def _compose(stack_path: Path, *args: str) -> str:
    cmd = ["podman-compose", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(stack_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace")


def register_stack_tools(server: Server, client: ContainerClient, settings: Settings) -> None:
    stacks_root = Path(settings.stacks_dir)

    def _stack_path(name: str) -> Path:
        p = stacks_root / name
        if not p.is_dir():
            raise ValueError(f"Stack not found: {name} (looked in {stacks_root})")
        return p

    @server.tool()
    async def stack_list() -> list[TextContent]:
        """List all stacks in the stacks directory."""
        if not stacks_root.exists():
            return [TextContent(type="text", text=f"Stacks directory not found: {stacks_root}")]
        stacks = [d.name for d in sorted(stacks_root.iterdir()) if d.is_dir()]
        return [TextContent(type="text", text="\n".join(stacks) or "No stacks found.")]

    @server.tool()
    async def stack_up(name: str) -> list[TextContent]:
        """Start a stack with podman-compose up -d."""
        out = await _compose(_stack_path(name), "up", "-d")
        return [TextContent(type="text", text=out)]

    @server.tool()
    async def stack_down(name: str, confirm: bool = False) -> list[TextContent]:
        """Stop a stack. Requires confirm=True."""
        if not confirm:
            return [TextContent(type="text", text="Pass confirm=True to bring the stack down.")]
        out = await _compose(_stack_path(name), "down")
        return [TextContent(type="text", text=out)]

    @server.tool()
    async def stack_pull(name: str) -> list[TextContent]:
        """Pull latest images for a stack."""
        out = await _compose(_stack_path(name), "pull")
        return [TextContent(type="text", text=out)]

    @server.tool()
    async def stack_restart(name: str) -> list[TextContent]:
        """Restart a stack (down then up)."""
        down = await _compose(_stack_path(name), "down")
        up = await _compose(_stack_path(name), "up", "-d")
        return [TextContent(type="text", text=f"--- down ---\n{down}\n--- up ---\n{up}")]

    @server.tool()
    async def compose_read(stack: str) -> list[TextContent]:
        """Read the compose.yaml for a stack."""
        p = _stack_path(stack)
        for fname in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"):
            f = p / fname
            if f.exists():
                return [TextContent(type="text", text=f.read_text())]
        return [TextContent(type="text", text=f"No compose file found in {p}")]

    @server.tool()
    async def compose_write(stack: str, content: str) -> list[TextContent]:
        """Write/replace the compose.yaml for a stack."""
        p = _stack_path(stack) / "compose.yaml"
        p.write_text(content)
        return [TextContent(type="text", text=f"Written: {p}")]

    @server.tool()
    async def compose_validate(stack: str) -> list[TextContent]:
        """Dry-run validate a stack compose file."""
        out = await _compose(_stack_path(stack), "up", "--dry-run")
        return [TextContent(type="text", text=out)]

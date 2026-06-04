"""Stack management tools — delegates to arr-agent when available."""

from __future__ import annotations

import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.helper.client import HelperClient, HelperUnavailableError, unavailable_message
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.tools.utils import is_owned_by_current_user

log = logging.getLogger(__name__)

_QUADLET_DIR = Path.home() / ".config" / "containers" / "systemd"
_QUADLET_MSG = (
    "This stack is managed by systemd quadlets, not a compose file. "
    "Use the quadlet_* tools (quadlet_read, quadlet_write, quadlet_list) to manage it."
)


def _has_quadlet_for(name: str) -> bool:
    """Return True if a .container quadlet file exists matching the stack name."""
    if not _QUADLET_DIR.exists():
        return False
    return any(_QUADLET_DIR.glob(f"{name}.container")) or any(
        _QUADLET_DIR.glob(f"{name}-*.container")
    )


def register_stack_tools(server: FastMCP, client: ContainerClient, settings: Settings) -> None:
    """Register stack management tools with the MCP server."""
    stacks_root = Path(settings.compose_dir)
    helper = HelperClient(settings.helper_socket)

    allowed = settings.allowed_stacks

    def _stack_path(name: str) -> Path:
        if allowed and name not in allowed:
            raise ValueError(
                f"Stack '{name}' is not in the allowed stacks list. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )
        p = stacks_root / name
        if not p.is_dir() or not is_owned_by_current_user(p):
            raise ValueError(f"Stack not found: {name} (looked in {stacks_root})")
        return p

    async def _helper_call(op: str, **args: str) -> list[TextContent]:
        """Call the helper and return TextContent, or degrade gracefully."""
        try:
            result = await helper.call(op, **args)
            return [TextContent(type="text", text=result.output)]
        except HelperUnavailableError:
            log.warning("arr-agent unavailable for op=%s", op)
            return [TextContent(type="text", text=unavailable_message())]

    @server.tool()
    async def stack_list() -> list[TextContent]:
        """List all stacks in the stacks directory."""
        if not stacks_root.exists():
            return [TextContent(type="text", text=f"Stacks directory not found: {stacks_root}")]
        stacks = [
            d.name
            for d in sorted(stacks_root.iterdir())
            if d.is_dir() and is_owned_by_current_user(d) and (not allowed or d.name in allowed)
        ]
        return [TextContent(type="text", text="\n".join(stacks) or "No stacks found.")]

    @server.tool()
    async def stack_up(name: str) -> list[TextContent]:
        """Start a stack via the host-side helper."""
        _stack_path(name)  # validate locally first
        return await _helper_call("stack_up", stack=name)

    @server.tool()
    async def stack_down(name: str, confirm: bool = False) -> list[TextContent]:
        """Stop a stack. Requires confirm=True."""
        if not confirm:
            return [TextContent(type="text", text="Pass confirm=True to bring the stack down.")]
        _stack_path(name)
        return await _helper_call("stack_down", stack=name)

    @server.tool()
    async def stack_pull(name: str) -> list[TextContent]:
        """Pull latest images for a stack via the host-side helper."""
        _stack_path(name)
        return await _helper_call("stack_pull", stack=name)

    @server.tool()
    async def stack_restart(name: str) -> list[TextContent]:
        """Restart a stack (down then up) via the host-side helper."""
        _stack_path(name)
        return await _helper_call("stack_restart", stack=name)

    @server.tool()
    async def compose_read(stack: str) -> list[TextContent]:
        """Read the compose.yaml for a stack."""
        p = _stack_path(stack)
        for fname in (
            "compose.yaml",
            "compose.yml",
            "docker-compose.yaml",
            "docker-compose.yml",
        ):
            f = p / fname
            if f.exists():
                return [TextContent(type="text", text=f.read_text())]
        if _has_quadlet_for(stack):
            return [TextContent(type="text", text=_QUADLET_MSG)]
        return [TextContent(type="text", text=f"No compose file found in {p}")]

    @server.tool()
    async def compose_write(stack: str, content: str) -> list[TextContent]:
        """Write/replace the compose.yaml for a stack."""
        if _has_quadlet_for(stack):
            return [TextContent(type="text", text=_QUADLET_MSG)]
        p = _stack_path(stack) / "compose.yaml"
        p.write_text(content)
        return [TextContent(type="text", text=f"Written: {p}")]

    @server.tool()
    async def compose_validate(stack: str) -> list[TextContent]:
        """Validate a stack compose file via the host-side helper."""
        if _has_quadlet_for(stack):
            return [TextContent(type="text", text=_QUADLET_MSG)]
        _stack_path(stack)
        return await _helper_call("compose_validate", stack=stack)

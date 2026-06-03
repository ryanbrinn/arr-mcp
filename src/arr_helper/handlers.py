"""Operation handlers for arr-agent."""

from __future__ import annotations

import logging
from pathlib import Path

from arr_helper.subprocess import run_command
from arr_helper.validation import (
    validate_content,
    validate_quadlet_name,
    validate_stack_name,
    validate_unit_name,
)

log = logging.getLogger(__name__)

STACKS_DIR = "/opt/stacks"
QUADLET_DIR = Path.home() / ".config" / "containers" / "systemd"


def _compose_file(stack: str) -> str:
    return f"{STACKS_DIR}/{stack}/compose.yaml"


async def handle_stack_up(args: dict[str, str]) -> tuple[int, str]:
    """Start a stack with podman-compose up -d."""
    stack = validate_stack_name(args.get("stack", ""))
    return await run_command("podman-compose", "-f", _compose_file(stack), "up", "-d")


async def handle_stack_down(args: dict[str, str]) -> tuple[int, str]:
    """Stop a stack with podman-compose down."""
    stack = validate_stack_name(args.get("stack", ""))
    return await run_command("podman-compose", "-f", _compose_file(stack), "down")


async def handle_stack_pull(args: dict[str, str]) -> tuple[int, str]:
    """Pull latest images for a stack."""
    stack = validate_stack_name(args.get("stack", ""))
    return await run_command("podman-compose", "-f", _compose_file(stack), "pull")


async def handle_stack_restart(args: dict[str, str]) -> tuple[int, str]:
    """Restart a stack (down then up)."""
    stack = validate_stack_name(args.get("stack", ""))
    down_code, down_out = await run_command("podman-compose", "-f", _compose_file(stack), "down")
    up_code, up_out = await run_command("podman-compose", "-f", _compose_file(stack), "up", "-d")
    combined = f"--- down ---\n{down_out}\n--- up ---\n{up_out}"
    return max(down_code, up_code), combined


async def handle_compose_validate(args: dict[str, str]) -> tuple[int, str]:
    """Dry-run validate a stack compose file."""
    stack = validate_stack_name(args.get("stack", ""))
    return await run_command("podman-compose", "-f", _compose_file(stack), "config")


async def handle_systemd_start(args: dict[str, str]) -> tuple[int, str]:
    """Start a systemd user unit."""
    unit = validate_unit_name(args.get("unit", ""))
    return await run_command("systemctl", "--user", "start", unit)


async def handle_systemd_stop(args: dict[str, str]) -> tuple[int, str]:
    """Stop a systemd user unit."""
    unit = validate_unit_name(args.get("unit", ""))
    return await run_command("systemctl", "--user", "stop", unit)


async def handle_systemd_restart(args: dict[str, str]) -> tuple[int, str]:
    """Restart a systemd user unit."""
    unit = validate_unit_name(args.get("unit", ""))
    return await run_command("systemctl", "--user", "restart", unit)


async def handle_systemd_status(args: dict[str, str]) -> tuple[int, str]:
    """Get status of a systemd user unit."""
    unit = validate_unit_name(args.get("unit", ""))
    return await run_command("systemctl", "--user", "status", unit)


async def handle_systemd_daemon_reload(args: dict[str, str]) -> tuple[int, str]:
    """Reload the systemd user daemon."""
    return await run_command("systemctl", "--user", "daemon-reload")


async def handle_quadlet_read(args: dict[str, str]) -> tuple[int, str]:
    """Read a quadlet .container file."""
    name = validate_quadlet_name(args.get("name", ""))
    path = QUADLET_DIR / f"{name}.container"
    if not path.exists():
        return 1, f"Quadlet not found: {path}"
    return 0, path.read_text()


async def handle_quadlet_write(args: dict[str, str]) -> tuple[int, str]:
    """Write a quadlet .container file."""
    name = validate_quadlet_name(args.get("name", ""))
    content = validate_content(args.get("content", ""))
    QUADLET_DIR.mkdir(parents=True, exist_ok=True)
    path = QUADLET_DIR / f"{name}.container"
    path.write_text(content)
    return 0, f"Written: {path}"


async def handle_quadlet_list(args: dict[str, str]) -> tuple[int, str]:
    """List all .container quadlet files."""
    if not QUADLET_DIR.exists():
        return 0, ""
    names = sorted(p.stem for p in QUADLET_DIR.glob("*.container"))
    return 0, "\n".join(names)


async def handle_quadlet_delete(args: dict[str, str]) -> tuple[int, str]:
    """Delete a quadlet .container file."""
    name = validate_quadlet_name(args.get("name", ""))
    path = QUADLET_DIR / f"{name}.container"
    if not path.exists():
        return 1, f"Quadlet not found: {path}"
    path.unlink()
    return 0, f"Deleted: {path}"


# Dispatch table — maps op name to handler function
HANDLERS: dict[
    str,
    object,  # Callable[[dict[str, str]], Awaitable[tuple[int, str]]]
] = {
    "stack_up": handle_stack_up,
    "stack_down": handle_stack_down,
    "stack_pull": handle_stack_pull,
    "stack_restart": handle_stack_restart,
    "compose_validate": handle_compose_validate,
    "systemd_start": handle_systemd_start,
    "systemd_stop": handle_systemd_stop,
    "systemd_restart": handle_systemd_restart,
    "systemd_status": handle_systemd_status,
    "systemd_daemon_reload": handle_systemd_daemon_reload,
    "quadlet_read": handle_quadlet_read,
    "quadlet_write": handle_quadlet_write,
    "quadlet_list": handle_quadlet_list,
    "quadlet_delete": handle_quadlet_delete,
}

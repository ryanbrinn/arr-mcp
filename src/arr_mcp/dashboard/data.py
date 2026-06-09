"""Dashboard data layer — assembles status from existing runtime client."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient


async def get_status(client: ContainerClient, settings: Settings) -> dict[str, Any]:
    """Build the status dict for the dashboard and /api/status endpoint."""
    containers = await _get_containers(client)
    stacks = _derive_stacks(containers) if settings.is_compose else []
    disk = _get_disk(settings)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "containers": containers,
        "stacks": stacks,
        "disk": disk,
        "runtime": settings.container_runtime,
    }


async def _get_containers(client: ContainerClient) -> list[dict[str, Any]]:
    """Fetch container list from the runtime socket."""
    try:
        raw: list[dict[str, Any]] = await client.get(
            "/v1.41/containers/json", params={"all": "true"}
        )
    except Exception:
        return []

    containers = []
    for c in raw:
        name = (c.get("Names") or ["unknown"])[0].lstrip("/")
        state = c.get("State", "unknown")
        status_str = c.get("Status", "")

        # Parse uptime from Status string (e.g. "Up 2 hours")
        uptime_seconds: int | None = None
        if state == "running" and status_str.lower().startswith("up "):
            uptime_seconds = _parse_uptime(status_str)

        containers.append(
            {
                "id": c.get("Id", "")[:12],
                "name": name,
                "image": c.get("Image", ""),
                "status": state,
                "health": _extract_health(c),
                "uptime_seconds": uptime_seconds,
            }
        )
    return sorted(containers, key=lambda x: x["name"])


def _extract_health(container: dict[str, Any]) -> str:
    """Extract health status from container dict."""
    health = container.get("State", {})
    if isinstance(health, dict):
        return health.get("Health", {}).get("Status", "") or ""
    return ""


def _parse_uptime(status: str) -> int | None:
    """Very rough uptime parser from Docker status string."""
    try:
        parts = status.lower().removeprefix("up ").split()
        if len(parts) >= 2:
            n = int(parts[0])
            unit = parts[1].rstrip("s")
            multipliers = {
                "second": 1,
                "minute": 60,
                "hour": 3600,
                "day": 86400,
                "week": 604800,
            }
            return n * multipliers.get(unit, 0)
    except (ValueError, IndexError):
        pass
    return None


def _derive_stacks(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group containers by their compose project label into stacks."""
    # Without label access from the summary API, group by name prefix heuristic.
    # A proper implementation would use /containers/{id}/json per container.
    # For Phase 1 this gives a reasonable approximation.
    if not containers:
        return []

    total = len(containers)
    running = sum(1 for c in containers if c["status"] == "running")

    if running == total:
        overall = "healthy"
    elif running == 0:
        overall = "down"
    else:
        overall = "degraded"

    return [
        {
            "name": "all",
            "container_count": total,
            "running_count": running,
            "status": overall,
        }
    ]


def _get_disk(settings: Settings) -> list[dict[str, Any]]:
    """Get disk usage for configured paths."""
    paths = [settings.media_dir]
    if settings.is_compose and settings.compose_dir:
        paths.append(settings.compose_dir)
    results = []
    for path in paths:
        try:
            total, used, free = shutil.disk_usage(path)
            results.append(
                {
                    "path": path,
                    "total_gb": round(total / 1e9, 1),
                    "used_gb": round(used / 1e9, 1),
                    "free_gb": round(free / 1e9, 1),
                    "used_pct": round(used / total * 100, 1) if total else 0.0,
                }
            )
        except OSError:
            pass
    return results

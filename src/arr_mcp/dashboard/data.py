"""Dashboard data layer — assembles status from existing runtime client."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any

import anyio

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient


async def get_status(client: ContainerClient, settings: Settings) -> dict[str, Any]:
    """Build the status dict for the dashboard and /api/status endpoint."""
    containers = await _get_containers(client)
    stacks = _derive_stacks(containers) if settings.is_compose else []
    disk = _get_disk(settings)
    alerts_recent = _get_recent_alerts(settings)
    upgrades = _get_upgrade_list(settings)
    connectivity = await _get_service_connectivity(settings)
    stats = _derive_stats(containers, disk, alerts_recent, upgrades)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "containers": containers,
        "stacks": stacks,
        "disk": disk,
        "alerts_recent": alerts_recent,
        "upgrades": upgrades,
        "connectivity": connectivity,
        "stats": stats,
        "runtime": settings.container_runtime,
    }


# ---------------------------------------------------------------------------
# Containers & stacks
# ---------------------------------------------------------------------------


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
    health = container.get("State", {})
    if isinstance(health, dict):
        return health.get("Health", {}).get("Status", "") or ""
    return ""


def _parse_uptime(status: str) -> int | None:
    try:
        parts = status.lower().removeprefix("up ").split()
        if len(parts) >= 2:
            n = int(parts[0])
            unit = parts[1].rstrip("s")
            multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
            return n * multipliers.get(unit, 0)
    except (ValueError, IndexError):
        pass
    return None


def _derive_stacks(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group containers into a summary stack entry."""
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


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def _get_disk(settings: Settings) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Service connectivity
# ---------------------------------------------------------------------------


async def _get_service_connectivity(settings: Settings) -> list[dict[str, Any]]:
    """Ping all configured services concurrently and return reachability status."""
    from arr_mcp.services.base import ServiceNotConfiguredError
    from arr_mcp.services.registry import ServiceRegistry

    registry = ServiceRegistry(settings.services_dir)
    available = registry.available()
    if not available:
        return []

    results: list[dict[str, Any]] = [{}] * len(available)

    async def _check(idx: int, name: str) -> None:
        try:
            svc_client = registry.get_client(name)
            with anyio.move_on_after(5.0):
                health = await svc_client.health()
                results[idx] = {
                    "name": name,
                    "reachable": health.ok,
                    "status": "ok" if health.ok else "unreachable",
                    "error": health.error if not health.ok else None,
                }
                return
            results[idx] = {"name": name, "reachable": False, "status": "timeout", "error": None}
        except ServiceNotConfiguredError:
            results[idx] = {
                "name": name,
                "reachable": False,
                "status": "unconfigured",
                "error": None,
            }
        except Exception as exc:
            results[idx] = {"name": name, "reachable": False, "status": "error", "error": str(exc)}

    async with anyio.create_task_group() as tg:
        for i, name in enumerate(available):
            tg.start_soon(_check, i, name)

    return results


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def _get_recent_alerts(settings: Settings) -> list[dict[str, Any]]:
    from arr_mcp.tasks.alerts import AlertStore

    store = AlertStore(settings.services_dir)
    alerts = store.recent_alerts(limit=5)
    return [
        {
            "rule": a.rule,
            "service": a.service,
            "severity": a.severity,
            "message": a.message,
            "fired_at": a.fired_at,
        }
        for a in alerts
    ]


# ---------------------------------------------------------------------------
# Upgrades
# ---------------------------------------------------------------------------


def _get_upgrade_list(settings: Settings) -> list[dict[str, Any]]:
    from arr_mcp.tasks.versions import VersionStore

    store = VersionStore(settings.services_dir)
    recs = store.get_recommendations()
    return [
        {
            "service": r.service,
            "current_version": r.current_version,
            "latest_version": r.latest_version,
            "risk": r.risk,
            "changelog_summary": r.changelog_summary[:120] if r.changelog_summary else "",
        }
        for r in recs
    ]


# ---------------------------------------------------------------------------
# Stats summary tiles
# ---------------------------------------------------------------------------


def _derive_stats(
    containers: list[dict[str, Any]],
    disk: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    upgrades: list[dict[str, Any]],
) -> dict[str, Any]:
    running = sum(1 for c in containers if c["status"] == "running")
    max_disk_pct = max((d["used_pct"] for d in disk), default=0.0)
    return {
        "containers_running": running,
        "containers_total": len(containers),
        "disk_max_pct": max_disk_pct,
        "alerts_count": len(alerts),
        "upgrades_count": len(upgrades),
    }

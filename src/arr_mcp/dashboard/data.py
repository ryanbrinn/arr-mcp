"""Dashboard data layer — assembles status from existing runtime client."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import anyio

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient

if TYPE_CHECKING:
    from arr_mcp.ai.provider import AIProvider


async def get_status(client: ContainerClient, settings: Settings) -> dict[str, Any]:
    """Build the status dict for the dashboard and /api/status endpoint."""
    containers = await _get_containers(client)
    stacks = _derive_stacks(containers) if settings.is_compose else []
    disk = _get_disk(settings)
    alerts_recent = _get_recent_alerts(settings)
    upgrades = _get_upgrade_list(settings)
    connectivity = await _get_service_connectivity(settings)
    media = await _get_media_stats(settings)
    stats = _derive_stats(containers, disk, alerts_recent, upgrades)

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "containers": containers,
        "stacks": stacks,
        "disk": disk,
        "alerts_recent": alerts_recent,
        "upgrades": upgrades,
        "connectivity": connectivity,
        "media": media,
        "stats": stats,
        "runtime": settings.container_runtime,
    }


def _detect_issues(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Return detected issues from status that warrant AI analysis."""
    issues: list[dict[str, Any]] = []

    for d in status.get("disk", []):
        if d.get("used_pct", 0) >= 85:
            issues.append(
                {
                    "type": "disk_pressure",
                    "context": {"path": d["path"], "used_pct": d["used_pct"]},
                }
            )
            break

    for svc in status.get("connectivity", []):
        if not svc.get("reachable") and svc.get("status") not in (
            "unconfigured",
            "timeout",
        ):
            issues.append(
                {
                    "type": "service_unreachable",
                    "context": {
                        "service": svc["name"],
                        "container_status": svc.get("status", "unknown"),
                    },
                }
            )
            break

    return issues


async def get_insights(
    status: dict[str, Any],
    ai_provider: AIProvider | None,
) -> list[dict[str, Any]]:
    """Generate AI insights for detected issues in the current status.

    Returns an empty list when no issues are detected or when all diagnose
    calls fail/time out.
    """
    from arr_mcp.ai.null import NullProvider
    from arr_mcp.dashboard.diagnose import diagnose

    issues = _detect_issues(status)
    if not issues:
        return []

    provider = ai_provider if ai_provider is not None else NullProvider()
    results: list[dict[str, Any]] = []

    for issue in issues[:2]:  # cap at 2 AI calls per render
        with anyio.move_on_after(10.0):
            try:
                result = await diagnose(provider, issue["type"], issue["context"])
                if result:
                    results.append(
                        {
                            "type": issue["type"],
                            "narrative": result.get("narrative", ""),
                            "remedies": result.get("remedies", []),
                        }
                    )
            except Exception:
                pass

    return results


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
# Media library stats
# ---------------------------------------------------------------------------


_ART_PALETTE = list(range(8))


def _series_badge(s: Any) -> str:
    real = [ss for ss in s.seasons if ss.season_number > 0]
    total_eps = sum(ss.episode_count for ss in real)
    total_files = sum(ss.episode_file_count for ss in real)
    if total_files == 0:
        return "wanted" if s.monitored else "unmonitored"
    if total_files >= total_eps > 0:
        return "complete"
    return "partial"


def _movie_badge(m: Any) -> str:
    if m.has_file:
        return "complete"
    return "wanted" if m.monitored else "unmonitored"


def _series_card(s: Any, idx: int) -> dict[str, Any]:
    real_seasons = [ss for ss in s.seasons if ss.season_number > 0]
    return {
        "id": s.id,
        "title": s.title,
        "year": s.year,
        "status": s.status,
        "monitored": s.monitored,
        "season_count": len(real_seasons),
        "seasons": [
            {
                "number": ss.season_number,
                "pct": (
                    int(ss.episode_file_count / ss.episode_count * 100)
                    if ss.episode_count
                    else 0
                ),
            }
            for ss in real_seasons
        ],
        "badge": _series_badge(s),
        "art": idx % 8,
        "eligible": False,
        "pending": False,
    }


def _movie_card(m: Any, idx: int) -> dict[str, Any]:
    return {
        "id": m.id,
        "title": m.title,
        "year": m.year,
        "status": m.status,
        "monitored": m.monitored,
        "has_file": m.has_file,
        "badge": _movie_badge(m),
        "art": idx % 8,
        "movie_file_id": m.movie_file_id,
        "eligible": False,
        "pending": False,
    }


async def _get_media_stats(settings: Settings) -> dict[str, Any]:
    """Fetch media library cards from Sonarr and Radarr."""
    from arr_mcp.services.base import ServiceNotConfiguredError
    from arr_mcp.services.registry import ServiceRegistry

    registry = ServiceRegistry(settings.services_dir)
    stats: dict[str, Any] = {
        "configured": False,
        "series_count": None,
        "movie_count": None,
        "wanted_count": 0,
        "series": [],
        "movies": [],
    }

    try:
        sonarr = registry.get_client("sonarr")
        stats["configured"] = True
        with anyio.move_on_after(8.0):
            result = await sonarr.get_series()  # type: ignore[attr-defined]
            if result.ok and isinstance(result.data, list):
                cards = [_series_card(s, i) for i, s in enumerate(result.data)]
                stats["series"] = cards
                stats["series_count"] = len(cards)
                stats["wanted_count"] += sum(1 for c in cards if c["badge"] == "wanted")
    except ServiceNotConfiguredError:
        pass
    except Exception:
        pass

    try:
        radarr = registry.get_client("radarr")
        stats["configured"] = True
        with anyio.move_on_after(8.0):
            result = await radarr.get_movies()  # type: ignore[attr-defined]
            if result.ok and isinstance(result.data, list):
                cards = [_movie_card(m, i) for i, m in enumerate(result.data)]
                _annotate_interest(cards, settings)
                stats["movies"] = cards
                stats["movie_count"] = len(cards)
                stats["wanted_count"] += sum(1 for c in cards if c["badge"] == "wanted")
    except ServiceNotConfiguredError:
        pass
    except Exception:
        pass

    return stats


def _annotate_interest(movie_cards: list[dict[str, Any]], settings: Settings) -> None:
    """Populate eligible/pending flags on movie cards from the interest store."""
    from arr_mcp.services.interests import InterestStore

    store = InterestStore(settings.services_dir)
    eligible_ids = set(store.get_eligible_for_deletion())
    pending_ids = set(store.get_pending_review())
    for card in movie_cards:
        fid = card.get("movie_file_id")
        if fid is not None:
            fid_str = str(fid)
            card["eligible"] = fid_str in eligible_ids
            card["pending"] = fid_str in pending_ids


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
            results[idx] = {
                "name": name,
                "reachable": False,
                "status": "timeout",
                "error": None,
            }
        except ServiceNotConfiguredError:
            results[idx] = {
                "name": name,
                "reachable": False,
                "status": "unconfigured",
                "error": None,
            }
        except Exception as exc:
            results[idx] = {
                "name": name,
                "reachable": False,
                "status": "error",
                "error": str(exc),
            }

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
            "changelog_summary": r.changelog_summary[:120]
            if r.changelog_summary
            else "",
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

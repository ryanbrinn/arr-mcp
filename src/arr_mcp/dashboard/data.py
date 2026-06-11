"""Dashboard data layer — assembles status from existing runtime client."""

from __future__ import annotations

import re
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
    connectivity = await _get_service_connectivity(settings, containers)
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


def _dots_for_states(
    states: dict[str, str], users: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build the per-user interest dot list for a card or season."""
    from arr_mcp.services.interests import InterestState

    return [
        {
            "user_id": u["id"],
            "username": u.get("title") or u.get("username", ""),
            "state": states.get(u["id"], InterestState.interested.value),
        }
        for u in users
    ]


def _aggregate_state(states: list[str]) -> str:
    """Collapse multiple per-episode states into a single season/series dot."""
    from arr_mcp.services.interests import InterestState

    if not states:
        return InterestState.interested.value
    if any(s == InterestState.interested.value for s in states):
        return InterestState.interested.value
    if all(s == InterestState.marked_deletion.value for s in states):
        return InterestState.marked_deletion.value
    return InterestState.watched.value


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


def _movie_download_info(item: Any) -> dict[str, Any]:
    """Build progress/status info for a movie's queue item."""
    raw = item.raw
    size = raw.get("size", 0)
    progress_pct = int((1 - item.size_left_bytes / size) * 100) if size else 0
    stalled = raw.get("trackedDownloadStatus", "") in ("warning", "error")
    if stalled:
        messages = [
            msg
            for sm in raw.get("statusMessages", [])
            for msg in sm.get("messages", [])
        ]
        detail = messages[0] if messages else raw.get("errorMessage") or "stalled"
        status_text = f"⚠ Stuck — {detail}"
    else:
        timeleft = raw.get("timeleft")
        status_text = f"~{timeleft} remaining" if timeleft else "Downloading…"
    return {
        "progress_pct": progress_pct,
        "stalled": stalled,
        "status_text": status_text,
    }


def _is_unwatched(user_dots: list[dict[str, Any]], has_content: bool) -> bool:
    """A card is "unwatched" if it has files but no user has touched it."""
    from arr_mcp.services.interests import InterestState

    if not has_content or not user_dots:
        return False
    return all(d["state"] == InterestState.interested.value for d in user_dots)


def _series_card(s: Any, idx: int, cache: dict[str, Any]) -> dict[str, Any]:
    real_seasons = [ss for ss in s.seasons if ss.season_number > 0]
    total_eps = sum(ss.episode_count for ss in real_seasons)
    total_files = sum(ss.episode_file_count for ss in real_seasons)
    users = cache.get("users", [])
    cached_seasons = cache.get("series", {}).get(str(s.id), {})

    series_states: dict[str, list[str]] = {}
    seasons = []
    for ss in real_seasons:
        episodes = cached_seasons.get(str(ss.season_number), [])
        season_states: dict[str, list[str]] = {}
        for ep in episodes:
            for user_id, state in ep.get("dots", {}).items():
                season_states.setdefault(user_id, []).append(state)
                series_states.setdefault(user_id, []).append(state)
        seasons.append(
            {
                "number": ss.season_number,
                "pct": (
                    int(ss.episode_file_count / ss.episode_count * 100)
                    if ss.episode_count
                    else 0
                ),
                "episodes": episodes,
                "user_dots": _dots_for_states(
                    {
                        uid: _aggregate_state(states)
                        for uid, states in season_states.items()
                    },
                    users,
                ),
            }
        )

    availability_pct = int(total_files / total_eps * 100) if total_eps else 0
    user_dots = _dots_for_states(
        {uid: _aggregate_state(states) for uid, states in series_states.items()},
        users,
    )
    return {
        "id": s.id,
        "title": s.title,
        "year": s.year,
        "status": s.status,
        "monitored": s.monitored,
        "season_count": len(real_seasons),
        "seasons": seasons,
        "episode_file_count": total_files,
        "availability_pct": availability_pct,
        "badge": _series_badge(s),
        "art": idx % 8,
        "poster_url": s.poster_url,
        "user_dots": user_dots,
        "eligible": False,
        "pending": False,
        "downloading": False,
        "unwatched": _is_unwatched(user_dots, availability_pct > 0),
    }


def _movie_card(m: Any, idx: int, cache: dict[str, Any]) -> dict[str, Any]:
    movie_dots = (
        cache.get("movies", {}).get(str(m.movie_file_id), {})
        if m.movie_file_id is not None
        else {}
    )
    user_dots = _dots_for_states(movie_dots, cache.get("users", []))
    return {
        "id": m.id,
        "title": m.title,
        "year": m.year,
        "status": m.status,
        "monitored": m.monitored,
        "has_file": m.has_file,
        "availability_pct": 100 if m.has_file else 0,
        "badge": _movie_badge(m),
        "art": idx % 8,
        "poster_url": m.poster_url,
        "movie_file_id": m.movie_file_id,
        "user_dots": user_dots,
        "eligible": False,
        "pending": False,
        "downloading": False,
        "download": None,
        "unwatched": _is_unwatched(user_dots, m.has_file),
    }


async def _get_media_stats(settings: Settings) -> dict[str, Any]:
    """Fetch media library cards from Sonarr and Radarr."""
    from arr_mcp.services.base import ServiceNotConfiguredError
    from arr_mcp.services.registry import ServiceRegistry
    from arr_mcp.tasks.media_interest import MediaInterestStore

    registry = ServiceRegistry(settings.services_dir)
    cache = MediaInterestStore(settings.services_dir).load()
    stats: dict[str, Any] = {
        "configured": False,
        "series_count": None,
        "movie_count": None,
        "wanted_count": 0,
        "episodes_count": 0,
        "downloading_count": 0,
        "eligible_gb": 0.0,
        "series": [],
        "movies": [],
        "interest_users": cache.get("users", []),
    }

    movie_files: list[Any] = []

    try:
        sonarr = registry.get_client("sonarr")
        stats["configured"] = True
        with anyio.move_on_after(8.0):
            result = await sonarr.get_series()  # type: ignore[attr-defined]
            if result.ok and isinstance(result.data, list):
                cards = [_series_card(s, i, cache) for i, s in enumerate(result.data)]
                _annotate_series_interest(cards, settings, cache)
                stats["series"] = cards
                stats["series_count"] = len(cards)
                stats["wanted_count"] += sum(1 for c in cards if c["badge"] == "wanted")
                stats["episodes_count"] += sum(c["episode_file_count"] for c in cards)
        with anyio.move_on_after(8.0):
            queue_result = await sonarr.get_queue()  # type: ignore[attr-defined]
            if queue_result.ok and isinstance(queue_result.data, list):
                stats["downloading_count"] += len(queue_result.data)
                downloading_series = {
                    item.raw.get("seriesId") for item in queue_result.data
                }
                for card in stats["series"]:
                    card["downloading"] = card["id"] in downloading_series
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
                cards = [_movie_card(m, i, cache) for i, m in enumerate(result.data)]
                _annotate_movie_interest(cards, settings)
                stats["movies"] = cards
                stats["movie_count"] = len(cards)
                stats["wanted_count"] += sum(1 for c in cards if c["badge"] == "wanted")
        with anyio.move_on_after(8.0):
            files_result = await radarr.get_movie_files()  # type: ignore[attr-defined]
            if files_result.ok and isinstance(files_result.data, list):
                movie_files = files_result.data
        with anyio.move_on_after(8.0):
            queue_result = await radarr.get_queue()  # type: ignore[attr-defined]
            if queue_result.ok and isinstance(queue_result.data, list):
                stats["downloading_count"] += len(queue_result.data)
                downloading_movies = {
                    item.raw.get("movieId"): item for item in queue_result.data
                }
                for card in stats["movies"]:
                    item = downloading_movies.get(card["id"])
                    if item is None:
                        continue
                    card["downloading"] = True
                    info = _movie_download_info(item)
                    card["download"] = info
                    card["badge"] = "stalled" if info["stalled"] else "downloading"
    except ServiceNotConfiguredError:
        pass
    except Exception:
        pass

    stats["eligible_gb"] = _eligible_gb(settings, cache, movie_files)

    return stats


def _eligible_gb(
    settings: Settings, cache: dict[str, Any], movie_files: list[Any]
) -> float:
    """Total size of files marked eligible for deletion, in GB."""
    from arr_mcp.services.interests import InterestStore

    eligible_ids = set(InterestStore(settings.services_dir).get_eligible_for_deletion())
    total_bytes = 0
    for seasons in cache.get("series", {}).values():
        for episodes in seasons.values():
            for ep in episodes:
                fid = ep.get("episode_file_id")
                if fid is not None and str(fid) in eligible_ids:
                    total_bytes += ep.get("size_bytes", 0)
    for mf in movie_files:
        if str(mf.id) in eligible_ids:
            total_bytes += mf.size
    return round(total_bytes / 1_000_000_000, 1)


def _annotate_movie_interest(
    movie_cards: list[dict[str, Any]], settings: Settings
) -> None:
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


def _annotate_series_interest(
    series_cards: list[dict[str, Any]], settings: Settings, cache: dict[str, Any]
) -> None:
    """Populate eligible/pending flags on series cards from the interest store.

    A series is "eligible" when every on-disk episode file across all of its
    seasons is eligible for deletion, and "pending" when at least one episode
    file is pending admin review.
    """
    from arr_mcp.services.interests import InterestStore

    store = InterestStore(settings.services_dir)
    eligible_ids = set(store.get_eligible_for_deletion())
    pending_ids = set(store.get_pending_review())
    cached_series = cache.get("series", {})
    for card in series_cards:
        ef_ids = [
            str(ep["episode_file_id"])
            for season_eps in cached_series.get(str(card["id"]), {}).values()
            for ep in season_eps
            if ep.get("episode_file_id") is not None
        ]
        card["eligible"] = bool(ef_ids) and all(e in eligible_ids for e in ef_ids)
        card["pending"] = any(e in pending_ids for e in ef_ids)


# ---------------------------------------------------------------------------
# Service connectivity
# ---------------------------------------------------------------------------


async def _get_service_connectivity(
    settings: Settings, containers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ping all configured services concurrently and return reachability status.

    Known services with a running container but no credentials configured
    (e.g. Plex before its token has been set up) are included with status
    "unconfigured" so they remain visible.
    """
    from arr_mcp.services.base import ServiceNotConfiguredError
    from arr_mcp.services.registry import ServiceRegistry
    from arr_mcp.tools.services import KNOWN_SERVICES

    registry = ServiceRegistry(settings.services_dir)
    available = registry.available()

    container_names = [c["name"].lower() for c in containers]
    unconfigured = [
        svc
        for svc in KNOWN_SERVICES
        if svc not in available and any(svc in name for name in container_names)
    ]

    if not available and not unconfigured:
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

    results.extend(
        {"name": svc, "reachable": False, "status": "unconfigured", "error": None}
        for svc in unconfigured
    )

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


# Boilerplate branch-switching notice that linuxserver/Sonarr-style release
# notes append, which gives no insight into what actually changed.
_GENERIC_BRANCH_NOTE_RE = re.compile(
    r"To receive (further )?(pre-release|beta|final)?[\s\S]*?branch to \**\w+\**\.?",
    re.IGNORECASE,
)

_RISK_GUIDANCE: dict[str, str] = {
    "major": (
        "Major version upgrade — may include breaking changes. "
        "Review the release notes before upgrading."
    ),
    "minor": (
        "Minor version upgrade — adds new features and is expected "
        "to be backward compatible."
    ),
    "patch": "Patch upgrade — bug fixes only, low risk to apply.",
    "unknown": "Update available. Review the release notes before upgrading.",
}


def _format_upgrade_notes(risk: str, changelog_summary: str) -> str:
    """Return user-facing upgrade notes describing impact and next steps."""
    cleaned = _GENERIC_BRANCH_NOTE_RE.sub("", changelog_summary or "")
    cleaned = cleaned.strip(" \t\n\r*-•").strip()
    guidance = _RISK_GUIDANCE.get(risk, _RISK_GUIDANCE["unknown"])
    if cleaned:
        return f"{guidance} {cleaned[:240]}"
    return guidance


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
            "changelog_summary": _format_upgrade_notes(r.risk, r.changelog_summary),
            "upgrade_command": r.upgrade_command,
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

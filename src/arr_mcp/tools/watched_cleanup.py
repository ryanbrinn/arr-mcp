"""Watched content cleanup tools — preview and delete watched non-current seasons."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tools.plex import (
    PlexEpisode,
    PlexUser,
    get_all_watched_episodes,
    get_home_users,
    read_plex_token,
)
from arr_mcp.tools.services import KNOWN_SERVICES

log = logging.getLogger(__name__)

_SONARR_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Sonarr API helpers
# ---------------------------------------------------------------------------


async def _sonarr_get(base_url: str, api_key: str, path: str) -> object:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}{path}",
            headers={"X-Api-Key": api_key},
            timeout=_SONARR_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


async def _sonarr_delete(base_url: str, api_key: str, path: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{base_url}{path}",
            headers={"X-Api-Key": api_key},
            timeout=_SONARR_TIMEOUT,
        )
        resp.raise_for_status()


async def get_sonarr_series(base_url: str, api_key: str) -> list[dict]:  # type: ignore[type-arg]
    """Return all series from sonarr."""
    data = await _sonarr_get(base_url, api_key, "/api/v3/series")
    return data if isinstance(data, list) else []


async def get_sonarr_episodes(base_url: str, api_key: str, series_id: int) -> list[dict]:  # type: ignore[type-arg]
    """Return all episodes for a sonarr series."""
    data = await _sonarr_get(base_url, api_key, f"/api/v3/episode?seriesId={series_id}")
    return data if isinstance(data, list) else []


async def delete_sonarr_episode_file(base_url: str, api_key: str, file_id: int) -> None:
    """Delete a single episode file via sonarr."""
    await _sonarr_delete(base_url, api_key, f"/api/v3/episodefile/{file_id}")


# ---------------------------------------------------------------------------
# Core cleanup logic
# ---------------------------------------------------------------------------


@dataclass
class EpisodeToDelete:
    """An episode file that is a candidate for deletion."""

    sonarr_episode_id: int
    episode_file_id: int
    series_title: str
    season_number: int
    episode_number: int
    title: str
    watched_by: list[str] = field(default_factory=list)
    all_users_watched: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "sonarr_episode_id": self.sonarr_episode_id,
            "episode_file_id": self.episode_file_id,
            "series_title": self.series_title,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "title": self.title,
            "watched_by": self.watched_by,
            "all_users_watched": self.all_users_watched,
        }


def _build_watched_index(
    episodes: list[PlexEpisode],
) -> dict[tuple[str, int, int], list[str]]:
    """Return a dict keyed by (normalised_series_title, season, episode) → watched_by."""
    idx: dict[tuple[str, int, int], list[str]] = {}
    for ep in episodes:
        key = (ep.series_title.lower().strip(), ep.season_number, ep.episode_number)
        idx[key] = ep.watched_by
    return idx


def _find_deletable_episodes(
    sonarr_series: list[dict],  # type: ignore[type-arg]
    sonarr_episodes: dict[int, list[dict]],  # type: ignore[type-arg]
    watched_index: dict[tuple[str, int, int], list[str]],
    all_user_names: list[str],
) -> list[EpisodeToDelete]:
    """Compute the list of episodes eligible for deletion.

    Rules:
    - Only episodes in non-current seasons (season < max season for the series)
    - Season 0 (specials) is always skipped
    - Episode must have a file on disk (episode_file_id > 0)
    - ALL household users must have watched the episode
    """
    candidates: list[EpisodeToDelete] = []

    for series in sonarr_series:
        series_id = series.get("id")
        series_title = series.get("title", "")
        episodes = sonarr_episodes.get(series_id, [])

        # Find the highest season number (excluding specials)
        season_numbers = {
            ep.get("seasonNumber", 0) for ep in episodes if ep.get("seasonNumber", 0) > 0
        }
        if not season_numbers:
            continue
        max_season = max(season_numbers)

        for ep in episodes:
            season = ep.get("seasonNumber", 0)
            if season == 0 or season >= max_season:
                continue
            file_id = ep.get("episodeFileId", 0)
            if not file_id:
                continue

            ep_num = ep.get("episodeNumber", 0)
            plex_key = (series_title.lower().strip(), season, ep_num)
            watched_by = watched_index.get(plex_key, [])

            all_watched = bool(all_user_names) and set(all_user_names).issubset(set(watched_by))

            candidates.append(
                EpisodeToDelete(
                    sonarr_episode_id=ep.get("id", 0),
                    episode_file_id=file_id,
                    series_title=series_title,
                    season_number=season,
                    episode_number=ep_num,
                    title=ep.get("title", ""),
                    watched_by=watched_by,
                    all_users_watched=all_watched,
                )
            )

    return candidates


def _resolve_plex_url(settings: Settings) -> str | None:
    """Return the local Plex base URL by reading from the plex service dir config."""
    plex_info = KNOWN_SERVICES.get("plex")
    if plex_info is None:
        return None
    plex_dir = Path(settings.services_dir) / "plex"
    if not plex_dir.exists():
        return None
    return f"http://localhost:{plex_info.default_port}"


def _resolve_plex_token(settings: Settings) -> str | None:
    plex_dir = Path(settings.services_dir) / "plex"
    return read_plex_token(plex_dir)


def _resolve_sonarr_url_and_key(settings: Settings) -> tuple[str, str] | None:
    """Return (base_url, api_key) for sonarr by reading its config.xml."""
    import xml.etree.ElementTree as ET

    sonarr_dir = Path(settings.services_dir) / "sonarr"
    config_path = sonarr_dir / "config.xml"
    if not config_path.exists():
        return None
    try:
        root = ET.parse(str(config_path)).getroot()
        config = {child.tag: (child.text or "").strip() for child in root}
    except ET.ParseError:
        return None
    api_key = config.get("ApiKey", "").strip()
    port = config.get("Port", "8989").strip() or "8989"
    if not api_key:
        return None
    return f"http://localhost:{port}", api_key


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_watched_cleanup_tools(server: FastMCP, settings: Settings) -> None:
    """Register watched content cleanup MCP tools."""

    @server.tool()
    async def watched_cleanup_preview() -> list[TextContent]:
        """Preview which watched episodes from non-current seasons would be deleted.

        Queries Plex for all users' watch history and cross-references with
        Sonarr to find episodes that:
        - Belong to a non-current season (not the highest season number)
        - Have been watched by ALL household users
        - Still have a file on disk

        Returns JSON with a list of candidate episodes and a summary. No files
        are deleted — use watched_cleanup_delete(confirm=True) to apply.
        """
        return await _run_cleanup(settings, dry_run=True)

    @server.tool()
    async def watched_cleanup_delete(confirm: bool = False) -> list[TextContent]:
        """Delete watched episodes from non-current seasons via Sonarr.

        Applies the same rules as watched_cleanup_preview: only removes
        episodes from non-current seasons where ALL household users have
        watched the episode. Requires confirm=True to proceed.

        Args:
            confirm: Must be True to delete files. Defaults to False (preview only).
        """
        if not confirm:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Pass confirm=True to delete watched non-current season episodes. "
                        "Run watched_cleanup_preview first to review what will be removed."
                    ),
                )
            ]
        return await _run_cleanup(settings, dry_run=False)


async def _run_cleanup(settings: Settings, *, dry_run: bool) -> list[TextContent]:
    """Core logic shared by preview and delete tools."""
    errors: list[str] = []

    # Resolve Plex connection
    plex_url = _resolve_plex_url(settings)
    plex_token = _resolve_plex_token(settings)
    if not plex_token:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": (
                            "Plex token not found. Set PLEX_TOKEN env var or ensure "
                            "Preferences.xml exists in the plex service directory."
                        )
                    }
                ),
            )
        ]
    if not plex_url:
        plex_url = f"http://localhost:{KNOWN_SERVICES['plex'].default_port}"

    # Resolve Sonarr connection
    sonarr_creds = _resolve_sonarr_url_and_key(settings)
    if sonarr_creds is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": (
                            "Sonarr config not found or ApiKey missing. "
                            "Ensure sonarr has started and its config.xml is readable."
                        )
                    }
                ),
            )
        ]
    sonarr_url, sonarr_key = sonarr_creds

    # Fetch Plex users and watch history
    try:
        users: list[PlexUser] = await get_home_users(plex_url, plex_token)
        all_user_names = [u.username for u in users]
        watched_episodes = await get_all_watched_episodes(plex_url, users)
    except Exception as exc:
        log.warning("Plex fetch error: %s", exc)
        errors.append(f"Plex error: {exc}")
        users = []
        all_user_names = []
        watched_episodes = []

    watched_index = _build_watched_index(watched_episodes)

    # Fetch Sonarr data
    try:
        sonarr_series = await get_sonarr_series(sonarr_url, sonarr_key)
    except Exception as exc:
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": f"Sonarr series fetch failed: {exc}"}),
            )
        ]

    sonarr_eps: dict[int, list[dict]] = {}  # type: ignore[type-arg]
    for series in sonarr_series:
        sid = series.get("id")
        if sid is None:
            continue
        try:
            sonarr_eps[sid] = await get_sonarr_episodes(sonarr_url, sonarr_key, int(sid))
        except Exception as exc:
            log.warning("Could not fetch episodes for series %s: %s", sid, exc)

    candidates = _find_deletable_episodes(sonarr_series, sonarr_eps, watched_index, all_user_names)
    deletable = [c for c in candidates if c.all_users_watched]

    deleted_count = 0
    delete_errors: list[str] = []
    if not dry_run:
        for ep in deletable:
            try:
                await delete_sonarr_episode_file(sonarr_url, sonarr_key, ep.episode_file_id)
                deleted_count += 1
            except Exception as exc:
                delete_errors.append(
                    f"Failed to delete {ep.series_title} S{ep.season_number:02d}E"
                    f"{ep.episode_number:02d}: {exc}"
                )

    result: dict[str, object] = {
        "dry_run": dry_run,
        "plex_users": all_user_names,
        "candidates": [c.to_dict() for c in deletable],
        "total_eligible": len(deletable),
    }
    if not dry_run:
        result["deleted"] = deleted_count
        result["delete_errors"] = delete_errors
    if errors:
        result["warnings"] = errors

    return [TextContent(type="text", text=json.dumps(result))]

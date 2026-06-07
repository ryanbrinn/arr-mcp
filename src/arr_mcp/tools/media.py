"""Watched content cleanup MCP tools."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.services.models import Episode, EpisodeFile, Series
from arr_mcp.services.plex import PlexClient, PlexEpisode, PlexUser
from arr_mcp.services.registry import ServiceRegistry
from arr_mcp.services.sonarr import SonarrClient

log = logging.getLogger(__name__)


@dataclass
class CleanupCandidate:
    """A single episode file that qualifies for cleanup."""

    series_title: str
    season_number: int
    episode_number: int
    episode_title: str
    episode_file_id: int
    file_path: str
    file_size_bytes: int
    watched_by: list[str] = field(default_factory=list)
    all_users_watched: bool = False


@dataclass
class CleanupResult:
    """Summary from a watched_cleanup_delete run."""

    deleted: list[dict] = field(default_factory=list)  # type: ignore[type-arg]
    skipped: list[dict] = field(default_factory=list)  # type: ignore[type-arg]
    delete_errors: list[dict] = field(default_factory=list)  # type: ignore[type-arg]


def _find_candidates(
    series_list: list[Series],
    episodes: list[Episode],
    episode_files: dict[int, EpisodeFile],
    watched_episodes: list[PlexEpisode],
    all_user_count: int,
) -> list[CleanupCandidate]:
    """Identify episode files that are safe to delete.

    Rules:
    - Season 0 (specials) always skipped
    - Only non-current seasons (season_number < max season for the series)
    - Episode must have a file on disk
    - ALL household users must have watched the episode
    """
    # Build a lookup: (series_title_lower, season, episode) → PlexEpisode
    plex_lookup: dict[tuple[str, int, int], PlexEpisode] = {}
    for ep in watched_episodes:
        key = (ep.series_title.lower(), ep.season_number, ep.episode_number)
        plex_lookup[key] = ep

    # Build max season per series
    max_season: dict[int, int] = {}
    for s in series_list:
        seasons_with_eps = [
            sn.season_number for sn in s.seasons if sn.season_number > 0 and sn.episode_count > 0
        ]
        if seasons_with_eps:
            max_season[s.id] = max(seasons_with_eps)

    candidates: list[CleanupCandidate] = []
    for episode in episodes:
        if episode.season_number == 0:
            continue
        if not episode.has_file or episode.episode_file_id is None:
            continue
        if max_season.get(episode.series_id, 0) <= episode.season_number:
            continue

        ef = episode_files.get(episode.episode_file_id)
        if ef is None:
            continue

        # Find series title for Plex lookup
        series_title = next((s.title for s in series_list if s.id == episode.series_id), "")
        plex_key = (series_title.lower(), episode.season_number, episode.episode_number)
        plex_ep = plex_lookup.get(plex_key)

        watched_by = plex_ep.watched_by if plex_ep else []
        all_watched = len(watched_by) >= all_user_count and all_user_count > 0

        if all_watched:
            candidates.append(
                CleanupCandidate(
                    series_title=series_title,
                    season_number=episode.season_number,
                    episode_number=episode.episode_number,
                    episode_title=episode.title,
                    episode_file_id=episode.episode_file_id,
                    file_path=ef.path,
                    file_size_bytes=ef.size,
                    watched_by=watched_by,
                    all_users_watched=True,
                )
            )

    return candidates


def register_media_tools(server: FastMCP, settings: Settings) -> None:
    """Register watched content cleanup tools with the MCP server."""
    registry = ServiceRegistry(settings.services_dir)

    @server.tool()
    async def watched_cleanup_preview() -> list[TextContent]:
        """Preview episode files that can be safely deleted.

        Identifies non-current-season episodes that ALL household Plex users
        have watched and that have a file on disk in Sonarr. Season 0 (specials)
        is always excluded. Returns a dry-run candidate list — no files are deleted.
        """
        try:
            sonarr = cast(SonarrClient, registry.get_client("sonarr"))
            plex = cast(PlexClient, registry.get_client("plex"))
        except Exception as exc:
            return [TextContent(type="text", text=f"Service not configured: {exc}")]

        series_result = await sonarr.get_series()
        if not series_result.ok:
            return [TextContent(type="text", text=f"Sonarr error: {series_result.error}")]

        users_result = await plex.get_home_users()
        if not users_result.ok:
            return [TextContent(type="text", text=f"Plex error: {users_result.error}")]

        users: list[PlexUser] = users_result.data  # type: ignore[assignment]
        watched_result = await plex.get_all_watched_episodes(users)
        if not watched_result.ok:
            return [TextContent(type="text", text=f"Plex error: {watched_result.error}")]

        series_list: list[Series] = series_result.data  # type: ignore[assignment]
        all_user_count = len(users)
        watched: list[PlexEpisode] = watched_result.data  # type: ignore[assignment]

        all_episodes: list[Episode] = []
        all_files: dict[int, EpisodeFile] = {}

        for s in series_list:
            ep_result = await sonarr.get_episodes(s.id)
            if ep_result.ok:
                all_episodes.extend(ep_result.data)  # type: ignore[arg-type]
            ef_result = await sonarr.get_episode_files(s.id)
            if ef_result.ok:
                for ef in ef_result.data:  # type: ignore[union-attr]
                    all_files[ef.id] = ef

        candidates = _find_candidates(series_list, all_episodes, all_files, watched, all_user_count)

        result = {
            "dry_run": True,
            "candidate_count": len(candidates),
            "total_size_bytes": sum(c.file_size_bytes for c in candidates),
            "candidates": [asdict(c) for c in candidates],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def watched_cleanup_delete(confirm: bool = False) -> list[TextContent]:
        """Delete episode files for fully-watched non-current seasons.

        Applies the same rules as watched_cleanup_preview, then calls
        sonarr.delete_episode_file() for each candidate. Requires confirm=True
        to proceed — without it, returns a summary of what would be deleted.

        Args:
            confirm: Must be True to execute deletions.
        """
        if not confirm:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Pass confirm=True to execute deletions. "
                        "Run watched_cleanup_preview first to review candidates."
                    ),
                )
            ]

        try:
            sonarr = cast(SonarrClient, registry.get_client("sonarr"))
            plex = cast(PlexClient, registry.get_client("plex"))
        except Exception as exc:
            return [TextContent(type="text", text=f"Service not configured: {exc}")]

        series_result = await sonarr.get_series()
        if not series_result.ok:
            return [TextContent(type="text", text=f"Sonarr error: {series_result.error}")]

        users_result = await plex.get_home_users()
        if not users_result.ok:
            return [TextContent(type="text", text=f"Plex error: {users_result.error}")]

        users: list[PlexUser] = users_result.data  # type: ignore[assignment]
        watched_result = await plex.get_all_watched_episodes(users)
        if not watched_result.ok:
            return [TextContent(type="text", text=f"Plex error: {watched_result.error}")]

        series_list: list[Series] = series_result.data  # type: ignore[assignment]
        all_user_count = len(users)
        watched: list[PlexEpisode] = watched_result.data  # type: ignore[assignment]

        all_episodes: list[Episode] = []
        all_files: dict[int, EpisodeFile] = {}

        for s in series_list:
            ep_result = await sonarr.get_episodes(s.id)
            if ep_result.ok:
                all_episodes.extend(ep_result.data)  # type: ignore[arg-type]
            ef_result = await sonarr.get_episode_files(s.id)
            if ef_result.ok:
                for ef in ef_result.data:  # type: ignore[union-attr]
                    all_files[ef.id] = ef

        candidates = _find_candidates(series_list, all_episodes, all_files, watched, all_user_count)

        cleanup = CleanupResult()
        for candidate in candidates:
            delete_result = await sonarr.delete_episode_file(candidate.episode_file_id)
            entry = {
                "series_title": candidate.series_title,
                "season_number": candidate.season_number,
                "episode_number": candidate.episode_number,
                "episode_file_id": candidate.episode_file_id,
                "file_path": candidate.file_path,
                "file_size_bytes": candidate.file_size_bytes,
            }
            if delete_result.ok:
                cleanup.deleted.append(entry)
            else:
                cleanup.delete_errors.append({**entry, "error": delete_result.error})

        result = {
            "deleted_count": len(cleanup.deleted),
            "error_count": len(cleanup.delete_errors),
            "total_freed_bytes": sum(d["file_size_bytes"] for d in cleanup.deleted),
            "deleted": cleanup.deleted,
            "delete_errors": cleanup.delete_errors,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

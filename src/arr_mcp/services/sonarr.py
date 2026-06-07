"""SonarrClient — Sonarr-specific API methods."""

from __future__ import annotations

import logging

from arr_mcp.services.arr import ArrClient
from arr_mcp.services.base import ApiResult
from arr_mcp.services.models import Episode, EpisodeFile, SeasonSummary, Series

log = logging.getLogger(__name__)


class SonarrClient(ArrClient):
    """HTTP client for the Sonarr API."""

    async def get_series(self) -> ApiResult:
        """Fetch all series in the Sonarr library."""
        result = await self.get("/api/v3/series")
        if result.ok and isinstance(result.data, list):
            result.data = [_parse_series(r) for r in result.data]
        return result

    async def get_episodes(self, series_id: int) -> ApiResult:
        """Fetch all episodes for a series."""
        result = await self.get("/api/v3/episode", seriesId=str(series_id))
        if result.ok and isinstance(result.data, list):
            result.data = [_parse_episode(r) for r in result.data]
        return result

    async def get_episode_files(self, series_id: int) -> ApiResult:
        """Fetch all on-disk episode files for a series."""
        result = await self.get("/api/v3/episodefile", seriesId=str(series_id))
        if result.ok and isinstance(result.data, list):
            result.data = [_parse_episode_file(r) for r in result.data]
        return result

    async def delete_episode_file(self, file_id: int) -> ApiResult:
        """Delete an episode file by its ID.

        Logs the file_id before issuing the delete for auditability.
        """
        log.info("Deleting episode file id=%d", file_id)
        return await self.delete(f"/api/v3/episodefile/{file_id}")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_series(raw: dict) -> Series:  # type: ignore[type-arg]
    seasons = [
        SeasonSummary(
            season_number=s.get("seasonNumber", 0),
            episode_count=s.get("statistics", {}).get("totalEpisodeCount", 0),
            episode_file_count=s.get("statistics", {}).get("episodeFileCount", 0),
        )
        for s in raw.get("seasons", [])
    ]
    return Series(
        id=raw.get("id", 0),
        title=raw.get("title", ""),
        path=raw.get("path", ""),
        seasons=seasons,
    )


def _parse_episode(raw: dict) -> Episode:  # type: ignore[type-arg]
    return Episode(
        id=raw.get("id", 0),
        series_id=raw.get("seriesId", 0),
        season_number=raw.get("seasonNumber", 0),
        episode_number=raw.get("episodeNumber", 0),
        title=raw.get("title", ""),
        has_file=raw.get("hasFile", False),
        episode_file_id=raw.get("episodeFileId") or None,
    )


def _parse_episode_file(raw: dict) -> EpisodeFile:  # type: ignore[type-arg]
    return EpisodeFile(
        id=raw.get("id", 0),
        series_id=raw.get("seriesId", 0),
        season_number=raw.get("seasonNumber", 0),
        path=raw.get("path", ""),
        size=raw.get("size", 0),
    )

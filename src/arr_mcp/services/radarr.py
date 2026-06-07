"""RadarrClient — Radarr-specific API methods."""

from __future__ import annotations

import logging

from arr_mcp.services.arr import ArrClient
from arr_mcp.services.base import ApiResult
from arr_mcp.services.models import Movie, MovieFile

log = logging.getLogger(__name__)


class RadarrClient(ArrClient):
    """HTTP client for the Radarr API."""

    async def get_movies(self) -> ApiResult:
        """Fetch all movies in the Radarr library."""
        result = await self.get("/api/v3/movie")
        if result.ok and isinstance(result.data, list):
            result.data = [_parse_movie(r) for r in result.data]
        return result

    async def get_movie_files(self) -> ApiResult:
        """Fetch all on-disk movie files tracked by Radarr."""
        result = await self.get("/api/v3/moviefile")
        if result.ok and isinstance(result.data, list):
            result.data = [_parse_movie_file(r) for r in result.data]
        return result

    async def delete_movie_file(self, file_id: int) -> ApiResult:
        """Delete a movie file by its ID.

        Logs the file_id before issuing the delete for auditability.
        """
        log.info("Deleting movie file id=%d", file_id)
        return await self.delete(f"/api/v3/moviefile/{file_id}")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_movie(raw: dict) -> Movie:  # type: ignore[type-arg]
    return Movie(
        id=raw.get("id", 0),
        title=raw.get("title", ""),
        path=raw.get("path", ""),
        has_file=raw.get("hasFile", False),
        movie_file_id=raw.get("movieFileId") or None,
    )


def _parse_movie_file(raw: dict) -> MovieFile:  # type: ignore[type-arg]
    return MovieFile(
        id=raw.get("id", 0),
        movie_id=raw.get("movieId", 0),
        path=raw.get("path", ""),
        size=raw.get("size", 0),
    )

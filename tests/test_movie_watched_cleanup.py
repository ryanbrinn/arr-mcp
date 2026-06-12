"""Tests for movie watched content cleanup tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arr_mcp.services.base import ApiResult
from arr_mcp.services.interests import InterestState, InterestStore
from arr_mcp.services.models import Movie, MovieFile
from arr_mcp.services.plex import PlexMovie, PlexUser
from arr_mcp.tools.media import (
    MovieCleanupCandidate,
    _apply_movie_interest_gate,
    _find_movie_candidates,
)

# ---------------------------------------------------------------------------
# Helpers — build mock service clients
# ---------------------------------------------------------------------------


def _movie(
    id: int,
    title: str,
    year: int = 2000,
    has_file: bool = True,
    file_id: int | None = None,
) -> Movie:
    return Movie(
        id=id,
        title=title,
        path=f"/media/movies/{title}",
        has_file=has_file,
        year=year,
        movie_file_id=file_id,
    )


def _movie_file(id: int, size: int = 5_000_000_000) -> MovieFile:
    return MovieFile(id=id, movie_id=1, path=f"/media/movies/file_{id}.mkv", size=size)


def _plex_movie(title: str, year: int, watched_by: list[str]) -> PlexMovie:
    return PlexMovie(
        rating_key=f"{title}-{year}",
        title=title,
        year=year,
        watched_by=watched_by,
    )


# ---------------------------------------------------------------------------
# _find_movie_candidates — pure business logic
# ---------------------------------------------------------------------------


def test_finds_candidate_when_all_watched() -> None:
    movies = [_movie(1, "Inception", year=2010, file_id=99)]
    files = {99: _movie_file(99)}
    watched = [_plex_movie("Inception", 2010, watched_by=["Alice"])]

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=1)
    assert len(candidates) == 1
    assert candidates[0].movie_title == "Inception"
    assert candidates[0].movie_file_id == 99
    assert candidates[0].all_users_watched is True


def test_skips_movie_without_file() -> None:
    movies = [_movie(1, "Inception", year=2010, has_file=False, file_id=None)]
    files: dict[int, MovieFile] = {}
    watched = [_plex_movie("Inception", 2010, watched_by=["Alice"])]

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=1)
    assert candidates == []


def test_skips_when_not_all_users_watched() -> None:
    movies = [_movie(1, "Inception", year=2010, file_id=99)]
    files = {99: _movie_file(99)}
    watched = [_plex_movie("Inception", 2010, watched_by=["Alice"])]

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=2)
    assert candidates == []


def test_movie_title_matching_is_case_insensitive() -> None:
    movies = [_movie(1, "Inception", year=2010, file_id=99)]
    files = {99: _movie_file(99)}
    watched = [_plex_movie("inception", 2010, watched_by=["Alice"])]

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=1)
    assert len(candidates) == 1


def test_unwatched_movie_not_included() -> None:
    movies = [_movie(1, "Inception", year=2010, file_id=99)]
    files = {99: _movie_file(99)}
    watched: list[PlexMovie] = []

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=1)
    assert candidates == []


def test_multiple_candidates_across_movies() -> None:
    movies = [
        _movie(1, "Movie A", year=2001, file_id=99),
        _movie(2, "Movie B", year=2002, file_id=100),
    ]
    files = {
        99: _movie_file(99),
        100: _movie_file(100),
    }
    watched = [
        _plex_movie("Movie A", 2001, watched_by=["Alice"]),
        _plex_movie("Movie B", 2002, watched_by=["Alice"]),
    ]

    candidates = _find_movie_candidates(movies, files, watched, all_user_count=1)
    assert len(candidates) == 2


# ---------------------------------------------------------------------------
# _apply_movie_interest_gate
# ---------------------------------------------------------------------------


def test_interest_gate_syncs_watched_state(tmp_path: Path) -> None:
    """After running the gate, watch history is persisted to the interest store."""
    store = InterestStore(str(tmp_path))
    users = [PlexUser("u1", "alice", "Alice", "tok")]
    candidates = [
        MovieCleanupCandidate(
            movie_title="Inception",
            movie_file_id=42,
            file_path="/media/inception.mkv",
            file_size_bytes=5_000_000_000,
            watched_by=["Alice"],
            all_users_watched=True,
        )
    ]
    eligible, protected = _apply_movie_interest_gate(candidates, users, store)
    assert len(eligible) == 1
    assert len(protected) == 0
    record = store.get("42", "u1")
    assert record.state == InterestState.watched


def test_interest_gate_blocks_interested_user(tmp_path: Path) -> None:
    """A user who watched but later set interested state blocks deletion."""
    store = InterestStore(str(tmp_path))
    users = [PlexUser("u1", "alice", "Alice", "tok")]
    store.set("42", "u1", InterestState.interested)

    candidates = [
        MovieCleanupCandidate(
            movie_title="Inception",
            movie_file_id=42,
            file_path="/media/inception.mkv",
            file_size_bytes=5_000_000_000,
            watched_by=["Alice"],
            all_users_watched=True,
        )
    ]
    eligible, protected = _apply_movie_interest_gate(candidates, users, store)
    assert len(eligible) == 0
    assert len(protected) == 1


def test_interest_gate_allows_marked_deletion(tmp_path: Path) -> None:
    """A user who explicitly marked deletion keeps the movie eligible."""
    store = InterestStore(str(tmp_path))
    users = [PlexUser("u1", "alice", "Alice", "tok")]
    store.set("42", "u1", InterestState.marked_deletion)

    candidates = [
        MovieCleanupCandidate(
            movie_title="Inception",
            movie_file_id=42,
            file_path="/media/inception.mkv",
            file_size_bytes=5_000_000_000,
            watched_by=["Alice"],
            all_users_watched=True,
        )
    ]
    eligible, protected = _apply_movie_interest_gate(candidates, users, store)
    assert len(eligible) == 1
    assert len(protected) == 0


# ---------------------------------------------------------------------------
# movie_watched_cleanup_preview / movie_watched_cleanup_delete — MCP tools
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry(tmp_path: Path) -> MagicMock:
    """Return a mock ServiceRegistry pre-configured with Radarr + Plex clients."""
    radarr = AsyncMock()
    plex = AsyncMock()

    movies = [_movie(1, "Inception", year=2010, file_id=99)]
    files = [_movie_file(99, size=2_000_000_000)]
    watched = [_plex_movie("Inception", 2010, watched_by=["Alice"])]
    users = [PlexUser("1", "alice", "Alice", "tok")]

    radarr.get_movies.return_value = ApiResult(ok=True, data=movies)
    radarr.get_movie_files.return_value = ApiResult(ok=True, data=files)

    plex.get_home_users.return_value = ApiResult(ok=True, data=users)
    plex.get_all_watched_movies.return_value = ApiResult(ok=True, data=watched)

    registry = MagicMock()
    registry.get_client.side_effect = lambda name: radarr if name == "radarr" else plex
    return registry


@pytest.mark.anyio
async def test_preview_returns_dry_run_flag(
    mock_registry: MagicMock, tmp_path: Path
) -> None:
    import json

    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.media import register_media_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    with patch("arr_mcp.tools.media.ServiceRegistry", return_value=mock_registry):
        register_media_tools(server, settings)

    tool_fn = next(
        t
        for t in server._tool_manager._tools.values()
        if t.name == "movie_watched_cleanup_preview"
    )
    result = await tool_fn.fn()
    assert isinstance(result, list)
    payload = json.loads(result[0].text)
    assert payload["dry_run"] is True
    assert payload["candidate_count"] == 1


@pytest.mark.anyio
async def test_delete_without_confirm_returns_prompt(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.media import register_media_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    mock_reg = MagicMock()

    with patch("arr_mcp.tools.media.ServiceRegistry", return_value=mock_reg):
        register_media_tools(server, settings)

    tool_fn = next(
        t
        for t in server._tool_manager._tools.values()
        if t.name == "movie_watched_cleanup_delete"
    )
    result = await tool_fn.fn(confirm=False)
    assert "confirm=True" in result[0].text
    mock_reg.get_client.assert_not_called()


@pytest.mark.anyio
async def test_delete_with_confirm_deletes_eligible_files(
    mock_registry: MagicMock, tmp_path: Path
) -> None:
    import json

    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.media import register_media_tools

    radarr = mock_registry.get_client("radarr")
    radarr.delete_movie_file.return_value = ApiResult(ok=True, data=None)

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    with patch("arr_mcp.tools.media.ServiceRegistry", return_value=mock_registry):
        register_media_tools(server, settings)

    tool_fn = next(
        t
        for t in server._tool_manager._tools.values()
        if t.name == "movie_watched_cleanup_delete"
    )
    result = await tool_fn.fn(confirm=True)
    payload = json.loads(result[0].text)
    assert payload["deleted_count"] == 1
    radarr.delete_movie_file.assert_awaited_once_with(99)

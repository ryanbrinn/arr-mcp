"""Tests for watched content cleanup tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arr_mcp.services.base import ApiResult
from arr_mcp.services.models import Episode, EpisodeFile, SeasonSummary, Series
from arr_mcp.services.plex import PlexEpisode, PlexUser
from arr_mcp.tools.media import _find_candidates

# ---------------------------------------------------------------------------
# Helpers — build mock service clients
# ---------------------------------------------------------------------------


def _series(
    id: int,
    title: str,
    seasons: list[tuple[int, int]],
) -> Series:
    """Build a Series with (season_number, episode_count) season tuples."""
    return Series(
        id=id,
        title=title,
        path=f"/media/tv/{title}",
        seasons=[SeasonSummary(s, e, e) for s, e in seasons],
    )


def _episode(
    id: int,
    series_id: int,
    season: int,
    ep_num: int,
    has_file: bool = True,
    file_id: int | None = None,
) -> Episode:
    return Episode(
        id=id,
        series_id=series_id,
        season_number=season,
        episode_number=ep_num,
        title=f"S{season:02d}E{ep_num:02d}",
        has_file=has_file,
        episode_file_id=file_id,
    )


def _file(
    id: int, series_id: int, season: int, size: int = 1_000_000_000
) -> EpisodeFile:
    return EpisodeFile(
        id=id,
        series_id=series_id,
        season_number=season,
        path=f"/media/tv/series_{series_id}/s{season:02d}e01.mkv",
        size=size,
    )


def _plex_ep(
    series_title: str, season: int, ep_num: int, watched_by: list[str]
) -> PlexEpisode:
    return PlexEpisode(
        rating_key=f"{series_title}-s{season}e{ep_num}",
        series_title=series_title,
        season_number=season,
        episode_number=ep_num,
        title=f"S{season:02d}E{ep_num:02d}",
        watched_by=watched_by,
    )


# ---------------------------------------------------------------------------
# _find_candidates — pure business logic
# ---------------------------------------------------------------------------


def test_finds_candidate_in_non_current_season() -> None:
    series = [_series(1, "Breaking Bad", [(1, 7), (2, 13), (5, 16)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=1)}
    watched = [_plex_ep("Breaking Bad", 1, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert len(candidates) == 1
    assert candidates[0].season_number == 1
    assert candidates[0].episode_file_id == 99


def test_skips_current_season() -> None:
    series = [_series(1, "Show", [(1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=2, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=2)}
    watched = [_plex_ep("Show", 2, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert candidates == []


def test_skips_season_zero() -> None:
    series = [_series(1, "Show", [(0, 3), (1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=0, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=0)}
    watched = [_plex_ep("Show", 0, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert candidates == []


def test_skips_episode_without_file() -> None:
    series = [_series(1, "Show", [(1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, has_file=False, file_id=None)]
    files: dict[int, EpisodeFile] = {}
    watched = [_plex_ep("Show", 1, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert candidates == []


def test_skips_when_not_all_users_watched() -> None:
    series = [_series(1, "Show", [(1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=1)}
    # Only one user watched; all_user_count=2
    watched = [_plex_ep("Show", 1, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=2)
    assert candidates == []


def test_all_users_watched_qualifies() -> None:
    series = [_series(1, "Show", [(1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=1)}
    watched = [_plex_ep("Show", 1, 1, watched_by=["Alice", "Bob"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=2)
    assert len(candidates) == 1
    assert set(candidates[0].watched_by) == {"Alice", "Bob"}
    assert candidates[0].all_users_watched is True


def test_series_title_matching_is_case_insensitive() -> None:
    series = [_series(1, "Breaking Bad", [(1, 7), (2, 13)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=1)}
    # Plex title in different case
    watched = [_plex_ep("breaking bad", 1, 1, watched_by=["Alice"])]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert len(candidates) == 1


def test_unwatched_episode_not_included() -> None:
    series = [_series(1, "Show", [(1, 6), (2, 8)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = {99: _file(99, 1, season=1)}
    watched: list[PlexEpisode] = []  # Nothing watched

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert candidates == []


def test_multiple_candidates_across_series() -> None:
    series = [
        _series(1, "Show A", [(1, 6), (2, 8)]),
        _series(2, "Show B", [(1, 4), (3, 10)]),
    ]
    episodes = [
        _episode(10, 1, season=1, ep_num=1, file_id=99),
        _episode(20, 2, season=1, ep_num=1, file_id=100),
    ]
    files = {
        99: _file(99, 1, season=1),
        100: _file(100, 2, season=1),
    }
    watched = [
        _plex_ep("Show A", 1, 1, watched_by=["Alice"]),
        _plex_ep("Show B", 1, 1, watched_by=["Alice"]),
    ]

    candidates = _find_candidates(series, episodes, files, watched, all_user_count=1)
    assert len(candidates) == 2


# ---------------------------------------------------------------------------
# watched_cleanup_preview — MCP tool (uses mock registry)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry(tmp_path: Path) -> MagicMock:
    """Return a mock ServiceRegistry pre-configured with Sonarr + Plex clients."""
    sonarr = AsyncMock()
    plex = AsyncMock()

    series = [_series(1, "Breaking Bad", [(1, 7), (2, 13)])]
    episodes = [_episode(10, 1, season=1, ep_num=1, file_id=99)]
    files = [_file(99, 1, season=1, size=2_000_000_000)]
    watched = [_plex_ep("Breaking Bad", 1, 1, watched_by=["Alice"])]
    users = [PlexUser("1", "alice", "Alice", "tok")]

    sonarr.get_series.return_value = ApiResult(ok=True, data=series)
    sonarr.get_episodes.return_value = ApiResult(ok=True, data=episodes)
    sonarr.get_episode_files.return_value = ApiResult(ok=True, data=files)

    plex.get_home_users.return_value = ApiResult(ok=True, data=users)
    plex.get_all_watched_episodes.return_value = ApiResult(ok=True, data=watched)

    registry = MagicMock()
    registry.get_client.side_effect = lambda name: sonarr if name == "sonarr" else plex
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
        if t.name == "watched_cleanup_preview"
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
        if t.name == "watched_cleanup_delete"
    )
    result = await tool_fn.fn(confirm=False)
    assert "confirm=True" in result[0].text
    mock_reg.get_client.assert_not_called()

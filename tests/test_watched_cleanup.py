"""Tests for the watched content cleanup tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.plex import PlexEpisode, PlexUser
from arr_mcp.tools.watched_cleanup import (
    _build_watched_index,
    _find_deletable_episodes,
    register_watched_cleanup_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server(settings: Settings) -> FastMCP:
    s = FastMCP("test")
    register_watched_cleanup_tools(s, settings)
    return s


def _make_sonarr_series(series_id: int, title: str) -> dict:  # type: ignore[type-arg]
    return {"id": series_id, "title": title}


def _make_episode(
    ep_id: int,
    series_id: int,
    season: int,
    episode: int,
    file_id: int = 1,
    title: str = "Ep",
) -> dict:  # type: ignore[type-arg]
    return {
        "id": ep_id,
        "seriesId": series_id,
        "seasonNumber": season,
        "episodeNumber": episode,
        "episodeFileId": file_id,
        "title": title,
    }


def _make_plex_ep(series: str, season: int, episode: int, watched_by: list[str]) -> PlexEpisode:
    return PlexEpisode(
        rating_key=f"{series}-s{season}e{episode}",
        title="Ep",
        series_title=series,
        season_number=season,
        episode_number=episode,
        watched_by=watched_by,
    )


# ---------------------------------------------------------------------------
# _build_watched_index
# ---------------------------------------------------------------------------


def test_build_watched_index_keys_by_normalised_title() -> None:
    eps = [_make_plex_ep("Breaking Bad", 1, 1, ["alice", "bob"])]
    idx = _build_watched_index(eps)
    assert ("breaking bad", 1, 1) in idx
    assert idx[("breaking bad", 1, 1)] == ["alice", "bob"]


def test_build_watched_index_empty() -> None:
    assert _build_watched_index([]) == {}


# ---------------------------------------------------------------------------
# _find_deletable_episodes
# ---------------------------------------------------------------------------


def test_find_deletable_skips_current_season() -> None:
    series = [_make_sonarr_series(1, "Breaking Bad")]
    episodes = {
        1: [
            _make_episode(10, 1, 1, 1, file_id=11),  # non-current
            _make_episode(20, 1, 2, 1, file_id=22),  # current (max)
        ]
    }
    watched = _build_watched_index(
        [
            _make_plex_ep("Breaking Bad", 1, 1, ["alice"]),
            _make_plex_ep("Breaking Bad", 2, 1, ["alice"]),
        ]
    )
    result = _find_deletable_episodes(series, episodes, watched, ["alice"])
    assert all(c.season_number == 1 for c in result)
    assert not any(c.season_number == 2 for c in result)


def test_find_deletable_skips_specials_season_zero() -> None:
    series = [_make_sonarr_series(1, "Show")]
    episodes = {
        1: [
            _make_episode(1, 1, 0, 1, file_id=5),  # special
            _make_episode(2, 1, 1, 1, file_id=6),  # non-current
            _make_episode(3, 1, 2, 1, file_id=7),  # current
        ]
    }
    watched = _build_watched_index([_make_plex_ep("Show", 1, 1, ["alice"])])
    result = _find_deletable_episodes(series, episodes, watched, ["alice"])
    assert not any(c.season_number == 0 for c in result)


def test_find_deletable_skips_episodes_without_file() -> None:
    series = [_make_sonarr_series(1, "Show")]
    episodes = {
        1: [
            _make_episode(1, 1, 1, 1, file_id=0),  # no file
            _make_episode(2, 1, 2, 1, file_id=9),  # current
        ]
    }
    watched = _build_watched_index([_make_plex_ep("Show", 1, 1, ["alice"])])
    result = _find_deletable_episodes(series, episodes, watched, ["alice"])
    assert result == []


def test_find_deletable_all_users_watched_flag() -> None:
    series = [_make_sonarr_series(1, "Show")]
    episodes = {
        1: [
            _make_episode(1, 1, 1, 1, file_id=10),
            _make_episode(2, 1, 1, 2, file_id=11),
            _make_episode(3, 1, 2, 1, file_id=12),  # current
        ]
    }
    watched = _build_watched_index(
        [
            _make_plex_ep("Show", 1, 1, ["alice", "bob"]),  # both watched
            _make_plex_ep("Show", 1, 2, ["alice"]),  # only alice
        ]
    )
    result = _find_deletable_episodes(series, episodes, watched, ["alice", "bob"])
    ep1 = next(c for c in result if c.episode_number == 1)
    ep2 = next(c for c in result if c.episode_number == 2)
    assert ep1.all_users_watched is True
    assert ep2.all_users_watched is False


def test_find_deletable_no_quorum_when_user_list_empty() -> None:
    series = [_make_sonarr_series(1, "Show")]
    episodes = {
        1: [
            _make_episode(1, 1, 1, 1, file_id=10),
            _make_episode(2, 1, 2, 1, file_id=11),  # current
        ]
    }
    watched = _build_watched_index([_make_plex_ep("Show", 1, 1, ["alice"])])
    result = _find_deletable_episodes(series, episodes, watched, [])
    assert all(not c.all_users_watched for c in result)


# ---------------------------------------------------------------------------
# watched_cleanup_preview tool (via MCP server)
# ---------------------------------------------------------------------------


async def test_watched_cleanup_preview_no_plex_token(server: FastMCP, settings: Settings) -> None:
    (Path(settings.services_dir) / "plex").mkdir()
    # No Preferences.xml, no env var
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("PLEX_TOKEN", None)
        result = await server.call_tool("watched_cleanup_preview", {})

    data = json.loads(result[0][0].text)
    assert "error" in data
    assert "token" in data["error"].lower()


async def test_watched_cleanup_preview_no_sonarr_config(
    server: FastMCP, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "tok")
    result = await server.call_tool("watched_cleanup_preview", {})
    data = json.loads(result[0][0].text)
    assert "error" in data
    assert "sonarr" in data["error"].lower()


async def test_watched_cleanup_preview_returns_candidates(
    server: FastMCP, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "tok")

    # Write minimal sonarr config.xml
    sonarr_dir = Path(settings.services_dir) / "sonarr"
    sonarr_dir.mkdir()
    (sonarr_dir / "config.xml").write_text(
        "<Config><ApiKey>testkey</ApiKey><Port>8989</Port></Config>"
    )

    sonarr_series = [{"id": 1, "title": "Breaking Bad"}]
    sonarr_episodes = [
        _make_episode(10, 1, 1, 1, file_id=55),
        _make_episode(20, 1, 2, 1, file_id=66),  # current season
    ]
    plex_users = [PlexUser("1", "alice", "tok")]
    plex_eps = [_make_plex_ep("Breaking Bad", 1, 1, ["alice"])]

    with (
        patch(
            "arr_mcp.tools.watched_cleanup.get_home_users",
            new=AsyncMock(return_value=plex_users),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_all_watched_episodes",
            new=AsyncMock(return_value=plex_eps),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_series",
            new=AsyncMock(return_value=sonarr_series),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_episodes",
            new=AsyncMock(return_value=sonarr_episodes),
        ),
    ):
        result = await server.call_tool("watched_cleanup_preview", {})

    data = json.loads(result[0][0].text)
    assert data["dry_run"] is True
    assert data["total_eligible"] == 1
    assert data["candidates"][0]["series_title"] == "Breaking Bad"
    assert data["candidates"][0]["season_number"] == 1
    assert data["candidates"][0]["all_users_watched"] is True


# ---------------------------------------------------------------------------
# watched_cleanup_delete tool
# ---------------------------------------------------------------------------


async def test_watched_cleanup_delete_requires_confirm(server: FastMCP) -> None:
    result = await server.call_tool("watched_cleanup_delete", {})
    assert "confirm=True" in result[0][0].text


async def test_watched_cleanup_delete_deletes_and_reports(
    server: FastMCP, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "tok")

    sonarr_dir = Path(settings.services_dir) / "sonarr"
    sonarr_dir.mkdir()
    (sonarr_dir / "config.xml").write_text(
        "<Config><ApiKey>testkey</ApiKey><Port>8989</Port></Config>"
    )

    sonarr_series = [{"id": 1, "title": "Breaking Bad"}]
    sonarr_episodes = [
        _make_episode(10, 1, 1, 1, file_id=55),
        _make_episode(20, 1, 2, 1, file_id=66),
    ]
    plex_users = [PlexUser("1", "alice", "tok")]
    plex_eps = [_make_plex_ep("Breaking Bad", 1, 1, ["alice"])]
    delete_mock = AsyncMock()

    with (
        patch(
            "arr_mcp.tools.watched_cleanup.get_home_users",
            new=AsyncMock(return_value=plex_users),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_all_watched_episodes",
            new=AsyncMock(return_value=plex_eps),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_series",
            new=AsyncMock(return_value=sonarr_series),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_episodes",
            new=AsyncMock(return_value=sonarr_episodes),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.delete_sonarr_episode_file",
            new=delete_mock,
        ),
    ):
        result = await server.call_tool("watched_cleanup_delete", {"confirm": True})

    data = json.loads(result[0][0].text)
    assert data["dry_run"] is False
    assert data["deleted"] == 1
    assert data["delete_errors"] == []
    delete_mock.assert_awaited_once()


async def test_watched_cleanup_delete_reports_partial_failure(
    server: FastMCP, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "tok")

    sonarr_dir = Path(settings.services_dir) / "sonarr"
    sonarr_dir.mkdir()
    (sonarr_dir / "config.xml").write_text(
        "<Config><ApiKey>testkey</ApiKey><Port>8989</Port></Config>"
    )

    sonarr_series = [{"id": 1, "title": "Breaking Bad"}]
    sonarr_episodes = [
        _make_episode(10, 1, 1, 1, file_id=55),
        _make_episode(20, 1, 2, 1, file_id=66),
    ]
    plex_users = [PlexUser("1", "alice", "tok")]
    plex_eps = [_make_plex_ep("Breaking Bad", 1, 1, ["alice"])]

    import httpx

    with (
        patch(
            "arr_mcp.tools.watched_cleanup.get_home_users",
            new=AsyncMock(return_value=plex_users),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_all_watched_episodes",
            new=AsyncMock(return_value=plex_eps),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_series",
            new=AsyncMock(return_value=sonarr_series),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.get_sonarr_episodes",
            new=AsyncMock(return_value=sonarr_episodes),
        ),
        patch(
            "arr_mcp.tools.watched_cleanup.delete_sonarr_episode_file",
            new=AsyncMock(side_effect=httpx.HTTPError("403")),
        ),
    ):
        result = await server.call_tool("watched_cleanup_delete", {"confirm": True})

    data = json.loads(result[0][0].text)
    assert data["deleted"] == 0
    assert len(data["delete_errors"]) == 1

"""Tests for MediaInterestStore and MediaInterestChecker."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from arr_mcp.services.base import ApiResult
from arr_mcp.services.interests import InterestState, InterestStore
from arr_mcp.services.models import Episode, EpisodeFile, Movie, SeasonSummary, Series
from arr_mcp.services.plex import PlexEpisode, PlexMovie, PlexUser
from arr_mcp.tasks.media_interest import (
    MediaInterestChecker,
    MediaInterestStore,
    _sync_movies,
    _sync_series,
    _user_dots,
)


@pytest.fixture
def settings(tmp_path):
    from arr_mcp.config import Settings

    return Settings(services_dir=str(tmp_path))


@pytest.fixture
def store(tmp_path):
    return MediaInterestStore(services_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# MediaInterestStore
# ---------------------------------------------------------------------------


def test_store_load_missing_file_returns_empty_dict(store) -> None:
    assert store.load() == {}


def test_store_save_and_load_roundtrip(store) -> None:
    data = {"users": [{"id": "1", "username": "ryan", "title": "Ryan"}]}
    store.save(data)
    assert store.load() == data


def test_store_load_invalid_json_returns_empty_dict(tmp_path, store) -> None:
    (tmp_path / ".arr-mcp-media-interest-cache.json").write_text("not json")
    assert store.load() == {}


# ---------------------------------------------------------------------------
# _user_dots
# ---------------------------------------------------------------------------


def test_user_dots_defaults_to_interested(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users = [PlexUser(id="1", username="ryan", title="Ryan", token="t")]
    dots = _user_dots("100", users, interest_store)
    assert dots == {"1": InterestState.interested.value}


def test_user_dots_reflects_set_state(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users = [PlexUser(id="1", username="ryan", title="Ryan", token="t")]
    interest_store.set(
        "100", "1", InterestState.marked_deletion, username="Ryan", content_type="movie"
    )
    dots = _user_dots("100", users, interest_store)
    assert dots == {"1": InterestState.marked_deletion.value}


# ---------------------------------------------------------------------------
# _sync_movies
# ---------------------------------------------------------------------------


def test_sync_movies_marks_watched_and_returns_dots(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users = [PlexUser(id="1", username="ryan", title="Ryan", token="t")]
    movies = [
        Movie(
            id=1,
            title="Inception",
            path="/movies/inception",
            has_file=True,
            year=2010,
            movie_file_id=42,
        ),
        Movie(id=2, title="No File", path="/movies/nf", has_file=False, year=2020),
    ]
    watched = [
        PlexMovie(rating_key="r1", title="Inception", year=2010, watched_by=["Ryan"])
    ]

    result = _sync_movies(movies, watched, users, interest_store)

    assert result == {"42": {"1": InterestState.watched.value}}
    assert interest_store.get("42", "1").state == InterestState.watched


def test_sync_movies_skips_movies_without_file_id(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users = [PlexUser(id="1", username="ryan", title="Ryan", token="t")]
    movies = [
        Movie(id=1, title="No File", path="/movies/nf", has_file=False, year=2020)
    ]

    result = _sync_movies(movies, [], users, interest_store)

    assert result == {}


# ---------------------------------------------------------------------------
# _sync_series
# ---------------------------------------------------------------------------


async def test_sync_series_builds_season_map_with_dots(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users = [PlexUser(id="1", username="ryan", title="Ryan", token="t")]
    series_list = [
        Series(
            id=10,
            title="Show",
            path="/tv/show",
            seasons=[
                SeasonSummary(season_number=1, episode_count=2, episode_file_count=2)
            ],
        )
    ]
    episodes = [
        Episode(
            id=1,
            series_id=10,
            season_number=1,
            episode_number=1,
            title="Pilot",
            has_file=True,
            episode_file_id=100,
        ),
        Episode(
            id=2,
            series_id=10,
            season_number=1,
            episode_number=2,
            title="Ep2",
            has_file=False,
            episode_file_id=None,
        ),
        Episode(
            id=3,
            series_id=10,
            season_number=0,
            episode_number=1,
            title="Special",
            has_file=True,
            episode_file_id=101,
        ),
    ]
    files = [EpisodeFile(id=100, series_id=10, season_number=1, path="/p", size=12345)]
    watched_episodes = [
        PlexEpisode(
            rating_key="r1",
            series_title="Show",
            season_number=1,
            episode_number=1,
            title="Pilot",
            watched_by=["Ryan"],
        )
    ]

    sonarr = AsyncMock()
    sonarr.get_episodes = AsyncMock(return_value=ApiResult(ok=True, data=episodes))
    sonarr.get_episode_files = AsyncMock(return_value=ApiResult(ok=True, data=files))

    result = await _sync_series(
        sonarr, series_list, watched_episodes, users, interest_store
    )

    assert set(result.keys()) == {"10"}
    season_1 = result["10"]["1"]
    assert len(season_1) == 2  # season 0 excluded

    pilot = season_1[0]
    assert pilot["episode_number"] == 1
    assert pilot["has_file"] is True
    assert pilot["size_bytes"] == 12345
    assert pilot["dots"] == {"1": InterestState.watched.value}

    ep2 = season_1[1]
    assert ep2["has_file"] is False
    assert ep2["dots"] == {}

    assert interest_store.get("100", "1").state == InterestState.watched


async def test_sync_series_skips_series_with_failed_fetch(tmp_path) -> None:
    interest_store = InterestStore(str(tmp_path))
    users: list[PlexUser] = []
    series_list = [Series(id=10, title="Show", path="/tv/show")]

    sonarr = AsyncMock()
    sonarr.get_episodes = AsyncMock(return_value=ApiResult(ok=False, error="boom"))
    sonarr.get_episode_files = AsyncMock(return_value=ApiResult(ok=True, data=[]))

    result = await _sync_series(sonarr, series_list, [], users, interest_store)

    assert result == {}


# ---------------------------------------------------------------------------
# MediaInterestChecker._poll
# ---------------------------------------------------------------------------


async def test_poll_does_nothing_when_plex_not_configured(settings) -> None:
    from arr_mcp.services.base import ServiceNotConfiguredError

    checker = MediaInterestChecker(settings)

    with patch(
        "arr_mcp.services.registry.ServiceRegistry.get_client",
        side_effect=ServiceNotConfiguredError("plex"),
    ):
        await checker._poll()

    assert MediaInterestStore(settings.services_dir).load() == {}


async def test_poll_writes_cache_with_movies_and_series(settings) -> None:
    user = PlexUser(id="1", username="ryan", title="Ryan", token="tok")

    plex = AsyncMock()
    plex.get_home_users = AsyncMock(return_value=ApiResult(ok=True, data=[user]))
    plex.get_all_watched_movies = AsyncMock(return_value=ApiResult(ok=True, data=[]))
    plex.get_all_watched_episodes = AsyncMock(return_value=ApiResult(ok=True, data=[]))

    radarr = AsyncMock()
    radarr.get_movies = AsyncMock(
        return_value=ApiResult(
            ok=True,
            data=[
                Movie(
                    id=1,
                    title="Inception",
                    path="/m",
                    has_file=True,
                    year=2010,
                    movie_file_id=42,
                )
            ],
        )
    )

    sonarr = AsyncMock()
    sonarr.get_series = AsyncMock(return_value=ApiResult(ok=True, data=[]))

    def get_client(name: str):
        return {"plex": plex, "radarr": radarr, "sonarr": sonarr}[name]

    checker = MediaInterestChecker(settings)
    with patch(
        "arr_mcp.services.registry.ServiceRegistry.get_client", side_effect=get_client
    ):
        await checker._poll()

    cache = MediaInterestStore(settings.services_dir).load()
    assert cache["users"] == [{"id": "1", "username": "ryan", "title": "Ryan"}]
    assert cache["movies"] == {"42": {"1": InterestState.interested.value}}
    assert cache["series"] == {}

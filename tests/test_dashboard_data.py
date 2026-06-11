"""Tests for dashboard data helpers."""

from __future__ import annotations

import pytest

from arr_mcp.dashboard.data import (
    _aggregate_state,
    _annotate_movie_interest,
    _annotate_series_interest,
    _dots_for_states,
    _eligible_gb,
    _format_upgrade_notes,
    _get_service_connectivity,
    _is_unwatched,
    _movie_card,
    _movie_download_info,
    _series_card,
)
from arr_mcp.services.arr import QueueItem
from arr_mcp.services.interests import InterestState
from arr_mcp.services.models import Movie, SeasonSummary, Series


def test_format_upgrade_notes_strips_generic_branch_note() -> None:
    changelog = (
        "*To receive further Pre-Release or final updates for a non-docker "
        "installation, please change the branch to **master**."
    )
    notes = _format_upgrade_notes("minor", changelog)
    assert "branch to" not in notes
    assert not notes.endswith("*")
    assert notes.startswith("Minor version upgrade")


def test_format_upgrade_notes_keeps_real_changelog() -> None:
    notes = _format_upgrade_notes("patch", "Fixed a crash on startup.")
    assert "Fixed a crash on startup." in notes
    assert notes.startswith("Patch upgrade")


def test_format_upgrade_notes_falls_back_to_guidance_only() -> None:
    notes = _format_upgrade_notes("major", "")
    assert notes == _format_upgrade_notes("major", "")
    assert "breaking changes" in notes


# ---------------------------------------------------------------------------
# _dots_for_states / _aggregate_state
# ---------------------------------------------------------------------------


def test_dots_for_states_defaults_to_interested() -> None:
    users = [{"id": "1", "username": "ryan", "title": "Ryan"}]
    dots = _dots_for_states({}, users)
    assert dots == [
        {"user_id": "1", "username": "Ryan", "state": InterestState.interested.value}
    ]


def test_dots_for_states_uses_given_state() -> None:
    users = [{"id": "1", "username": "ryan", "title": "Ryan"}]
    dots = _dots_for_states({"1": InterestState.watched.value}, users)
    assert dots[0]["state"] == InterestState.watched.value


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([], InterestState.interested.value),
        (["interested", "watched"], InterestState.interested.value),
        (["marked_deletion", "marked_deletion"], InterestState.marked_deletion.value),
        (["watched", "marked_deletion"], InterestState.watched.value),
        (["watched", "watched"], InterestState.watched.value),
    ],
)
def test_aggregate_state(states: list[str], expected: str) -> None:
    assert _aggregate_state(states) == expected


# ---------------------------------------------------------------------------
# _annotate_movie_interest / _annotate_series_interest
# ---------------------------------------------------------------------------


def test_annotate_movie_interest_marks_eligible_and_pending(tmp_path) -> None:
    from arr_mcp.config import Settings
    from arr_mcp.services.interests import InterestStore

    settings = Settings(services_dir=str(tmp_path))
    store = InterestStore(settings.services_dir)
    store.set(
        "100",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="movie",
    )

    cards = [{"movie_file_id": 100}, {"movie_file_id": 200}]
    _annotate_movie_interest(cards, settings)

    assert cards[0]["eligible"] is True
    assert cards[1]["eligible"] is False


def test_annotate_series_interest_eligible_when_all_files_eligible(tmp_path) -> None:
    from arr_mcp.config import Settings
    from arr_mcp.services.interests import InterestStore

    settings = Settings(services_dir=str(tmp_path))
    store = InterestStore(settings.services_dir)
    store.set(
        "100",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="episode",
    )
    store.set(
        "101",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="episode",
    )

    cache = {
        "series": {
            "10": {
                "1": [
                    {"episode_file_id": 100},
                    {"episode_file_id": 101},
                ]
            }
        }
    }
    cards = [{"id": 10}]
    _annotate_series_interest(cards, settings, cache)

    assert cards[0]["eligible"] is True
    assert cards[0]["pending"] is False


def test_annotate_series_interest_not_eligible_when_partial(tmp_path) -> None:
    from arr_mcp.config import Settings
    from arr_mcp.services.interests import InterestStore

    settings = Settings(services_dir=str(tmp_path))
    store = InterestStore(settings.services_dir)
    store.set(
        "100",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="episode",
    )

    cache = {
        "series": {
            "10": {
                "1": [
                    {"episode_file_id": 100},
                    {"episode_file_id": 101},
                ]
            }
        }
    }
    cards = [{"id": 10}]
    _annotate_series_interest(cards, settings, cache)

    assert cards[0]["eligible"] is False


def test_is_unwatched_true_when_no_one_has_state() -> None:
    dots = [
        {"user_id": "1", "username": "Ryan", "state": "interested"},
        {"user_id": "2", "username": "Sarah", "state": "interested"},
    ]
    assert _is_unwatched(dots, has_content=True) is True


def test_is_unwatched_false_when_someone_watched() -> None:
    dots = [
        {"user_id": "1", "username": "Ryan", "state": "watched"},
        {"user_id": "2", "username": "Sarah", "state": "interested"},
    ]
    assert _is_unwatched(dots, has_content=True) is False


def test_is_unwatched_false_without_content() -> None:
    dots = [{"user_id": "1", "username": "Ryan", "state": "interested"}]
    assert _is_unwatched(dots, has_content=False) is False


def test_is_unwatched_false_without_users() -> None:
    assert _is_unwatched([], has_content=True) is False


def test_eligible_gb_sums_eligible_episode_and_movie_bytes(tmp_path) -> None:
    from dataclasses import dataclass

    from arr_mcp.config import Settings
    from arr_mcp.services.interests import InterestStore

    settings = Settings(services_dir=str(tmp_path))
    store = InterestStore(settings.services_dir)
    store.set(
        "100",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="episode",
    )
    store.set(
        "200",
        "1",
        InterestState.marked_deletion,
        username="ryan",
        content_type="movie",
    )

    cache = {
        "series": {
            "10": {
                "1": [
                    {"episode_file_id": 100, "size_bytes": 1_000_000_000},
                    {"episode_file_id": 101, "size_bytes": 1_000_000_000},
                ]
            }
        }
    }

    @dataclass
    class _MovieFile:
        id: int
        size: int

    movie_files = [_MovieFile(id=200, size=500_000_000), _MovieFile(id=201, size=999)]

    assert _eligible_gb(settings, cache, movie_files) == 1.5


def test_series_card_includes_episode_file_count_and_defaults() -> None:
    series = Series(
        id=10,
        title="Show",
        path="/tv/show",
        year=2020,
        status="ended",
        seasons=[SeasonSummary(season_number=1, episode_count=2, episode_file_count=1)],
    )
    card = _series_card(series, 0, cache={})
    assert card["episode_file_count"] == 1
    assert card["downloading"] is False
    assert card["unwatched"] is False  # no interest_users in empty cache


def test_series_card_unwatched_when_users_present_and_no_state() -> None:
    series = Series(
        id=10,
        title="Show",
        path="/tv/show",
        year=2020,
        status="ended",
        seasons=[SeasonSummary(season_number=1, episode_count=1, episode_file_count=1)],
    )
    cache = {"users": [{"id": "1", "username": "ryan", "title": "Ryan"}]}
    card = _series_card(series, 0, cache)
    assert card["unwatched"] is True


def test_movie_card_includes_downloading_and_unwatched_defaults() -> None:
    movie = Movie(
        id=1, title="Inception", path="/movies/inception", has_file=True, year=2010
    )
    card = _movie_card(movie, 0, cache={})
    assert card["downloading"] is False
    assert card["unwatched"] is False


def test_movie_card_unwatched_when_users_present_and_no_state() -> None:
    movie = Movie(
        id=1, title="Inception", path="/movies/inception", has_file=True, year=2010
    )
    cache = {"users": [{"id": "1", "username": "ryan", "title": "Ryan"}]}
    card = _movie_card(movie, 0, cache)
    assert card["unwatched"] is True


def test_movie_download_info_in_progress() -> None:
    item = QueueItem(
        id=1,
        title="Alien: Romulus",
        status="downloading",
        tracked_download_state="downloading",
        size_left_bytes=33,
        raw={
            "movieId": 1,
            "size": 100,
            "sizeleft": 33,
            "trackedDownloadStatus": "ok",
            "timeleft": "00:40:00",
        },
    )
    info = _movie_download_info(item)
    assert info["progress_pct"] == 67
    assert info["stalled"] is False
    assert info["status_text"] == "~00:40:00 remaining"


def test_movie_download_info_stalled() -> None:
    item = QueueItem(
        id=2,
        title="Dune: Part Two",
        status="warning",
        tracked_download_state="importPending",
        size_left_bytes=77,
        raw={
            "movieId": 2,
            "size": 100,
            "sizeleft": 77,
            "trackedDownloadStatus": "warning",
            "statusMessages": [{"title": "Dune", "messages": ["SABnzbd warning"]}],
        },
    )
    info = _movie_download_info(item)
    assert info["progress_pct"] == 23
    assert info["stalled"] is True
    assert info["status_text"] == "⚠ Stuck — SABnzbd warning"


def test_movie_download_info_no_size_defaults_progress_to_zero() -> None:
    item = QueueItem(
        id=3,
        title="No Size",
        status="downloading",
        tracked_download_state="downloading",
        size_left_bytes=0,
        raw={"movieId": 3, "size": 0, "trackedDownloadStatus": "ok"},
    )
    info = _movie_download_info(item)
    assert info["progress_pct"] == 0
    assert info["status_text"] == "Downloading…"


def test_movie_card_default_download_is_none() -> None:
    movie = Movie(
        id=1, title="Inception", path="/movies/inception", has_file=True, year=2010
    )
    card = _movie_card(movie, 0, cache={})
    assert card["download"] is None


# ---------------------------------------------------------------------------
# _get_service_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_service_connectivity_includes_unconfigured_running_service(
    tmp_path,
) -> None:
    from arr_mcp.config import Settings

    settings = Settings(services_dir=str(tmp_path))
    containers = [{"name": "test-plex"}]

    results = await _get_service_connectivity(settings, containers)

    plex = next(r for r in results if r["name"] == "plex")
    assert plex["status"] == "unconfigured"
    assert plex["reachable"] is False


@pytest.mark.anyio
async def test_get_service_connectivity_omits_unrelated_unconfigured_services(
    tmp_path,
) -> None:
    from arr_mcp.config import Settings

    settings = Settings(services_dir=str(tmp_path))
    containers = [{"name": "test-plex"}]

    results = await _get_service_connectivity(settings, containers)

    assert all(r["name"] != "jellyfin" for r in results)

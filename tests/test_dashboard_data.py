"""Tests for dashboard data helpers."""

from __future__ import annotations

import pytest

from arr_mcp.dashboard.data import (
    _aggregate_state,
    _annotate_movie_interest,
    _annotate_series_interest,
    _dots_for_states,
    _format_upgrade_notes,
)
from arr_mcp.services.interests import InterestState


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

"""Tests for the Plex API client module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.tools.plex import (
    PlexUser,
    get_all_watched_episodes,
    get_all_watched_movies,
    get_home_users,
    get_watched_episodes,
    get_watched_movies,
    read_plex_token,
)

# ---------------------------------------------------------------------------
# read_plex_token
# ---------------------------------------------------------------------------


def test_read_plex_token_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "env-token-123")
    assert read_plex_token(tmp_path) == "env-token-123"


def test_read_plex_token_from_preferences_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    (tmp_path / "Preferences.xml").write_text('<Preferences PlexOnlineToken="xml-token-456" />')
    assert read_plex_token(tmp_path) == "xml-token-456"


def test_read_plex_token_env_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "env-wins")
    (tmp_path / "Preferences.xml").write_text('<Preferences PlexOnlineToken="xml-loses" />')
    assert read_plex_token(tmp_path) == "env-wins"


def test_read_plex_token_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    assert read_plex_token(tmp_path) is None


def test_read_plex_token_empty_attribute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    (tmp_path / "Preferences.xml").write_text('<Preferences PlexOnlineToken="" />')
    assert read_plex_token(tmp_path) is None


def test_read_plex_token_no_attribute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    (tmp_path / "Preferences.xml").write_text("<Preferences />")
    assert read_plex_token(tmp_path) is None


def test_read_plex_token_malformed_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    (tmp_path / "Preferences.xml").write_text("not xml at all")
    assert read_plex_token(tmp_path) is None


# ---------------------------------------------------------------------------
# get_home_users
# ---------------------------------------------------------------------------


def _mock_response(json_data: object, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


async def test_get_home_users_returns_all_users() -> None:
    payload = {
        "users": [
            {"id": 1, "username": "alice", "authToken": "tok-alice"},
            {"id": 2, "username": "bob", "authToken": "tok-bob"},
        ]
    }
    with patch("arr_mcp.tools.plex.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_mock_response(payload))

        users = await get_home_users("http://plex:32400", "owner-token")

    assert len(users) == 2
    assert users[0].username == "alice"
    assert users[0].token == "tok-alice"
    assert users[1].username == "bob"


async def test_get_home_users_fallback_on_error() -> None:
    server_info = {"MediaContainer": {"myPlexUsername": "ryan"}}
    call_count = 0

    async def fake_get(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "plex.tv" in url:
            raise httpx.HTTPError("forbidden")
        return _mock_response(server_info)

    with patch("arr_mcp.tools.plex.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get

        users = await get_home_users("http://plex:32400", "owner-token")

    assert len(users) == 1
    assert users[0].username == "ryan"
    assert users[0].token == "owner-token"


# ---------------------------------------------------------------------------
# get_watched_episodes / get_watched_movies
# ---------------------------------------------------------------------------


async def test_get_watched_episodes_parses_response() -> None:
    payload = {
        "MediaContainer": {
            "Metadata": [
                {
                    "ratingKey": "101",
                    "title": "Pilot",
                    "grandparentTitle": "Breaking Bad",
                    "parentIndex": 1,
                    "index": 1,
                },
                {
                    "ratingKey": "102",
                    "title": "Cat's in the Bag",
                    "grandparentTitle": "Breaking Bad",
                    "parentIndex": 1,
                    "index": 2,
                },
            ]
        }
    }
    with patch("arr_mcp.tools.plex.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_mock_response(payload))

        eps = await get_watched_episodes("http://plex:32400", "tok")

    assert len(eps) == 2
    assert eps[0]["series_title"] == "Breaking Bad"
    assert eps[0]["season_number"] == 1
    assert eps[0]["episode_number"] == 1


async def test_get_watched_episodes_returns_empty_on_error() -> None:
    with patch("arr_mcp.tools.plex.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("timeout"))

        eps = await get_watched_episodes("http://plex:32400", "tok")

    assert eps == []


async def test_get_watched_movies_parses_response() -> None:
    payload = {
        "MediaContainer": {
            "Metadata": [
                {"ratingKey": "200", "title": "Inception", "year": 2010},
            ]
        }
    }
    with patch("arr_mcp.tools.plex.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_mock_response(payload))

        movies = await get_watched_movies("http://plex:32400", "tok")

    assert len(movies) == 1
    assert movies[0]["title"] == "Inception"
    assert movies[0]["year"] == 2010


# ---------------------------------------------------------------------------
# get_all_watched_episodes / get_all_watched_movies
# ---------------------------------------------------------------------------


async def test_get_all_watched_episodes_aggregates_users() -> None:
    users = [
        PlexUser("1", "alice", "tok-alice"),
        PlexUser("2", "bob", "tok-bob"),
    ]
    alice_eps = [
        {
            "rating_key": "101",
            "title": "Pilot",
            "series_title": "BB",
            "season_number": 1,
            "episode_number": 1,
        },
    ]
    bob_eps = [
        {
            "rating_key": "101",
            "title": "Pilot",
            "series_title": "BB",
            "season_number": 1,
            "episode_number": 1,
        },
        {
            "rating_key": "102",
            "title": "Ep2",
            "series_title": "BB",
            "season_number": 1,
            "episode_number": 2,
        },
    ]

    async def fake_watched(base_url: str, token: str) -> list[dict]:
        return alice_eps if token == "tok-alice" else bob_eps

    with patch("arr_mcp.tools.plex.get_watched_episodes", side_effect=fake_watched):
        result = await get_all_watched_episodes("http://plex:32400", users)

    assert len(result) == 2
    ep101 = next(e for e in result if e.rating_key == "101")
    assert set(ep101.watched_by) == {"alice", "bob"}
    ep102 = next(e for e in result if e.rating_key == "102")
    assert ep102.watched_by == ["bob"]


async def test_get_all_watched_movies_aggregates_users() -> None:
    users = [
        PlexUser("1", "alice", "tok-alice"),
        PlexUser("2", "bob", "tok-bob"),
    ]
    both_movies = [{"rating_key": "200", "title": "Inception", "year": 2010}]

    async def fake_watched(base_url: str, token: str) -> list[dict]:
        return both_movies

    with patch("arr_mcp.tools.plex.get_watched_movies", side_effect=fake_watched):
        result = await get_all_watched_movies("http://plex:32400", users)

    assert len(result) == 1
    assert set(result[0].watched_by) == {"alice", "bob"}

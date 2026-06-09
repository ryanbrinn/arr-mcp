"""Tests for PlexClient."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import httpx
import pytest

from arr_mcp.services.plex import PlexClient, PlexEpisode, PlexMovie, PlexUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLEX_TV_USERS_URL = "https://plex.tv/api/v2/home/users"
_PLEX_TV_SWITCH_PATH_PREFIX = "/api/home/users/"


def _switch_xml(auth_token: str) -> bytes:
    return f'<?xml version="1.0"?><user id="1" authToken="{auth_token}"/>'.encode()


def _client(
    server_responses: dict[str, tuple[int, object]],
    plex_tv_response: tuple[int, object] | None = None,
    switch_tokens: dict[str, str] | None = None,
) -> PlexClient:
    """Build a PlexClient backed by a mock transport.

    ``switch_tokens`` maps a home user's id (as a string) to the personal
    access token returned by plex.tv's "switch user" endpoint — this is how
    PlexClient discovers per-user tokens, since the home users list itself
    does not include them.
    """
    switch_tokens = switch_tokens or {}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        path = req.url.path

        if _PLEX_TV_USERS_URL in url:
            if plex_tv_response is None:
                raise httpx.ConnectError("plex.tv unavailable")
            status, body = plex_tv_response
            return httpx.Response(
                status,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json"},
            )

        if path.startswith(_PLEX_TV_SWITCH_PATH_PREFIX) and path.endswith("/switch"):
            user_id = path[len(_PLEX_TV_SWITCH_PATH_PREFIX) : -len("/switch")]
            token = switch_tokens.get(user_id)
            if token is None:
                return httpx.Response(404, content=b"")
            return httpx.Response(200, content=_switch_xml(token))

        if path in server_responses:
            status, body = server_responses[path]
            return httpx.Response(
                status,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, content=b"{}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PlexClient("http://plex:32400", "owner-token", http=http)


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_plex_uses_x_plex_token_header() -> None:
    received: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        received.append(req.headers.get("x-plex-token", ""))
        return httpx.Response(
            200, content=b"{}", headers={"content-type": "application/json"}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PlexClient("http://plex:32400", "my-plex-token", http=http)
    await client.health()
    assert received[0] == "my-plex-token"


# ---------------------------------------------------------------------------
# get_home_users — plex.tv available
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_home_users_returns_user_list() -> None:
    # The real plex.tv/api/v2/home/users response does not include an
    # authToken — PlexClient must "switch" into each user to obtain one.
    plex_tv_payload = {
        "users": [
            {"id": 1, "username": "alice", "title": "Alice"},
            {"id": 2, "username": "bob", "title": "Bob"},
        ]
    }
    client = _client(
        {},
        plex_tv_response=(200, plex_tv_payload),
        switch_tokens={"1": "alice-token", "2": "bob-token"},
    )
    result = await client.get_home_users()
    assert result.ok
    assert len(result.data) == 2  # type: ignore[arg-type]
    user = result.data[0]  # type: ignore[index]
    assert isinstance(user, PlexUser)
    assert user.title == "Alice"
    assert user.token == "alice-token"


@pytest.mark.anyio
async def test_get_home_users_handles_switch_failure() -> None:
    """A user whose profile can't be switched into gets an empty token."""
    plex_tv_payload = {"users": [{"id": 1, "username": "alice", "title": "Alice"}]}
    client = _client({}, plex_tv_response=(200, plex_tv_payload), switch_tokens={})
    result = await client.get_home_users()
    assert result.ok
    users: list[PlexUser] = result.data  # type: ignore[assignment]
    assert users[0].token == ""


@pytest.mark.anyio
async def test_get_home_users_switches_concurrently() -> None:
    """Per-user "switch" calls run concurrently rather than one-at-a-time.

    Each handler invocation holds its slot open until every other expected
    invocation has also started — this only resolves if the client issues
    them all in parallel rather than awaiting them sequentially.
    """
    plex_tv_payload = {
        "users": [
            {"id": 1, "username": "alice", "title": "Alice"},
            {"id": 2, "username": "bob", "title": "Bob"},
            {"id": 3, "username": "carol", "title": "Carol"},
        ]
    }
    switch_tokens = {"1": "tok-alice", "2": "tok-bob", "3": "tok-carol"}
    in_flight = 0
    max_in_flight = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        url = str(req.url)
        path = req.url.path

        if _PLEX_TV_USERS_URL in url:
            return httpx.Response(
                200,
                content=json.dumps(plex_tv_payload).encode(),
                headers={"content-type": "application/json"},
            )

        if path.startswith(_PLEX_TV_SWITCH_PATH_PREFIX) and path.endswith("/switch"):
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await anyio.sleep(0.01)
            in_flight -= 1
            user_id = path[len(_PLEX_TV_SWITCH_PATH_PREFIX) : -len("/switch")]
            return httpx.Response(200, content=_switch_xml(switch_tokens[user_id]))

        return httpx.Response(404, content=b"{}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PlexClient("http://plex:32400", "owner-token", http=http)
    result = await client.get_home_users()

    assert result.ok
    users: list[PlexUser] = result.data  # type: ignore[assignment]
    assert {u.token for u in users} == {"tok-alice", "tok-bob", "tok-carol"}
    assert max_in_flight > 1


# ---------------------------------------------------------------------------
# get_home_users — plex.tv unavailable (fallback to owner)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_home_users_falls_back_to_owner_when_plex_tv_unavailable() -> None:
    client = _client({}, plex_tv_response=None)
    result = await client.get_home_users()
    assert result.ok
    users: list[PlexUser] = result.data  # type: ignore[assignment]
    assert len(users) == 1
    assert users[0].token == "owner-token"


# ---------------------------------------------------------------------------
# get_watched_episodes
# ---------------------------------------------------------------------------


def _episode_payload(*episodes: dict) -> dict:  # type: ignore[type-arg]
    return {"MediaContainer": {"Metadata": list(episodes)}}


@pytest.mark.anyio
async def test_get_watched_episodes_returns_dataclasses() -> None:
    payload = _episode_payload(
        {
            "ratingKey": "42",
            "grandparentTitle": "Breaking Bad",
            "parentIndex": 1,
            "index": 1,
            "title": "Pilot",
        }
    )
    client = _client({"/library/all": (200, payload)})
    result = await client.get_watched_episodes("some-token")
    assert result.ok
    ep = result.data[0]  # type: ignore[index]
    assert isinstance(ep, PlexEpisode)
    assert ep.series_title == "Breaking Bad"
    assert ep.season_number == 1
    assert ep.episode_number == 1


@pytest.mark.anyio
async def test_get_watched_episodes_empty_response() -> None:
    client = _client({"/library/all": (200, {"MediaContainer": {}})})
    result = await client.get_watched_episodes("token")
    assert result.ok
    assert result.data == []


# ---------------------------------------------------------------------------
# get_watched_movies
# ---------------------------------------------------------------------------


def _movie_payload(*movies: dict) -> dict:  # type: ignore[type-arg]
    return {"MediaContainer": {"Metadata": list(movies)}}


@pytest.mark.anyio
async def test_get_watched_movies_returns_dataclasses() -> None:
    payload = _movie_payload({"ratingKey": "99", "title": "Inception", "year": 2010})
    client = _client({"/library/all": (200, payload)})
    result = await client.get_watched_movies("some-token")
    assert result.ok
    movie = result.data[0]  # type: ignore[index]
    assert isinstance(movie, PlexMovie)
    assert movie.title == "Inception"
    assert movie.year == 2010


# ---------------------------------------------------------------------------
# get_all_watched_episodes — aggregation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_all_watched_episodes_aggregates_across_users() -> None:
    plex_tv_payload = {
        "users": [
            {"id": 1, "username": "alice", "title": "Alice"},
            {"id": 2, "username": "bob", "title": "Bob"},
        ]
    }
    ep = {
        "ratingKey": "42",
        "grandparentTitle": "Show",
        "parentIndex": 1,
        "index": 1,
        "title": "S01E01",
    }
    client = _client(
        {"/library/all": (200, _episode_payload(ep))},
        plex_tv_response=(200, plex_tv_payload),
        switch_tokens={"1": "tok-alice", "2": "tok-bob"},
    )
    result = await client.get_all_watched_episodes()
    assert result.ok
    episodes: list[PlexEpisode] = result.data  # type: ignore[assignment]
    assert len(episodes) == 1
    assert set(episodes[0].watched_by) == {"Alice", "Bob"}


@pytest.mark.anyio
async def test_get_all_watched_episodes_accepts_prefetched_users() -> None:
    """Passing ``users`` skips the internal get_home_users() round-trip."""
    plex_tv_calls = 0
    plex_tv_payload = {"users": [{"id": 1, "username": "alice", "title": "Alice"}]}
    ep = {
        "ratingKey": "42",
        "grandparentTitle": "Show",
        "parentIndex": 1,
        "index": 1,
        "title": "S01E01",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal plex_tv_calls
        url = str(req.url)
        path = req.url.path

        if _PLEX_TV_USERS_URL in url:
            plex_tv_calls += 1
            return httpx.Response(
                200,
                content=json.dumps(plex_tv_payload).encode(),
                headers={"content-type": "application/json"},
            )
        if path.startswith(_PLEX_TV_SWITCH_PATH_PREFIX) and path.endswith("/switch"):
            return httpx.Response(200, content=_switch_xml("tok-alice"))
        if path == "/library/all":
            return httpx.Response(
                200,
                content=json.dumps(_episode_payload(ep)).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, content=b"{}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PlexClient("http://plex:32400", "owner-token", http=http)

    users_result = await client.get_home_users()
    assert plex_tv_calls == 1
    users: list[PlexUser] = users_result.data  # type: ignore[assignment]

    result = await client.get_all_watched_episodes(users)
    assert result.ok
    episodes: list[PlexEpisode] = result.data  # type: ignore[assignment]
    assert episodes[0].watched_by == ["Alice"]
    assert plex_tv_calls == 1  # not re-fetched


@pytest.mark.anyio
async def test_get_all_watched_episodes_no_duplicates_for_unique_episodes() -> None:
    plex_tv_payload = {
        "users": [
            {"id": 1, "username": "alice", "title": "Alice"},
        ]
    }
    eps = [
        {
            "ratingKey": "1",
            "grandparentTitle": "Show A",
            "parentIndex": 1,
            "index": 1,
            "title": "ep1",
        },
        {
            "ratingKey": "2",
            "grandparentTitle": "Show B",
            "parentIndex": 1,
            "index": 1,
            "title": "ep1",
        },
    ]
    client = _client(
        {"/library/all": (200, _episode_payload(*eps))},
        plex_tv_response=(200, plex_tv_payload),
        switch_tokens={"1": "tok-alice"},
    )
    result = await client.get_all_watched_episodes()
    assert result.ok
    assert len(result.data) == 2  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_all_watched_movies — aggregation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_all_watched_movies_aggregates_across_users() -> None:
    plex_tv_payload = {
        "users": [
            {"id": 1, "username": "alice", "title": "Alice"},
            {"id": 2, "username": "bob", "title": "Bob"},
        ]
    }
    movie = {"ratingKey": "99", "title": "Inception", "year": 2010}
    client = _client(
        {"/library/all": (200, _movie_payload(movie))},
        plex_tv_response=(200, plex_tv_payload),
        switch_tokens={"1": "tok-alice", "2": "tok-bob"},
    )
    result = await client.get_all_watched_movies()
    assert result.ok
    movies: list[PlexMovie] = result.data  # type: ignore[assignment]
    assert len(movies) == 1
    assert set(movies[0].watched_by) == {"Alice", "Bob"}


# ---------------------------------------------------------------------------
# watched_by contains display names, not IDs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_watched_by_contains_display_names_not_ids() -> None:
    plex_tv_payload = {
        "users": [{"id": 12345, "username": "alice_login", "title": "Alice Smith"}]
    }
    ep = {
        "ratingKey": "1",
        "grandparentTitle": "Show",
        "parentIndex": 1,
        "index": 1,
        "title": "ep",
    }
    client = _client(
        {"/library/all": (200, _episode_payload(ep))},
        plex_tv_response=(200, plex_tv_payload),
        switch_tokens={"12345": "tok"},
    )
    result = await client.get_all_watched_episodes()
    episodes: list[PlexEpisode] = result.data  # type: ignore[assignment]
    assert episodes[0].watched_by == ["Alice Smith"]
    assert "12345" not in episodes[0].watched_by
    assert "alice_login" not in episodes[0].watched_by


# ---------------------------------------------------------------------------
# ServiceRegistry returns PlexClient
# ---------------------------------------------------------------------------


def test_registry_returns_plex_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arr_mcp.services.registry import ServiceRegistry

    monkeypatch.setenv("PLEX_TOKEN", "token")
    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("plex")
    assert isinstance(client, PlexClient)

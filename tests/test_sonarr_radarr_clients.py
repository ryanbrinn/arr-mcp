"""Tests for SonarrClient and RadarrClient."""

from __future__ import annotations

import json

import httpx
import pytest

from arr_mcp.services.models import Episode, EpisodeFile, Movie, MovieFile, Series
from arr_mcp.services.radarr import RadarrClient
from arr_mcp.services.sonarr import SonarrClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sonarr(responses: dict[str, tuple[int, object]]) -> SonarrClient:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        # Include query params for episode/episodefile requests
        full = path + ("?" + str(req.url.query) if req.url.query else "")
        for key, (status, body) in responses.items():
            if path == key or full.startswith(key):
                return httpx.Response(
                    status,
                    content=json.dumps(body).encode(),
                    headers={"content-type": "application/json"},
                )
        return httpx.Response(404, content=b"{}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SonarrClient("http://sonarr:8989", "key", http=http)


def _radarr(responses: dict[str, tuple[int, object]]) -> RadarrClient:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path in responses:
            status, body = responses[path]
            return httpx.Response(
                status,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, content=b"{}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RadarrClient("http://radarr:7878", "key", http=http)


# ---------------------------------------------------------------------------
# SonarrClient
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sonarr_get_series_returns_dataclasses() -> None:
    payload = [
        {
            "id": 1,
            "title": "Breaking Bad",
            "path": "/media/tv/Breaking Bad",
            "year": 2008,
            "status": "ended",
            "monitored": True,
            "seasons": [
                {
                    "seasonNumber": 1,
                    "statistics": {"totalEpisodeCount": 7, "episodeFileCount": 7},
                }
            ],
        }
    ]
    client = _sonarr({"/api/v3/series": (200, payload)})
    result = await client.get_series()
    assert result.ok
    assert isinstance(result.data, list)
    series = result.data[0]  # type: ignore[index]
    assert isinstance(series, Series)
    assert series.title == "Breaking Bad"
    assert series.year == 2008
    assert series.status == "ended"
    assert series.monitored is True
    assert len(series.seasons) == 1
    assert series.seasons[0].episode_count == 7


@pytest.mark.anyio
async def test_sonarr_get_episodes_returns_dataclasses() -> None:
    payload = [
        {
            "id": 10,
            "seriesId": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "title": "Pilot",
            "hasFile": True,
            "episodeFileId": 99,
        }
    ]
    client = _sonarr({"/api/v3/episode": (200, payload)})
    result = await client.get_episodes(1)
    assert result.ok
    ep = result.data[0]  # type: ignore[index]
    assert isinstance(ep, Episode)
    assert ep.title == "Pilot"
    assert ep.has_file is True
    assert ep.episode_file_id == 99


@pytest.mark.anyio
async def test_sonarr_get_episode_files_returns_dataclasses() -> None:
    payload = [
        {
            "id": 99,
            "seriesId": 1,
            "seasonNumber": 1,
            "path": "/media/tv/Breaking Bad/S01E01.mkv",
            "size": 1_500_000_000,
        }
    ]
    client = _sonarr({"/api/v3/episodefile": (200, payload)})
    result = await client.get_episode_files(1)
    assert result.ok
    ef = result.data[0]  # type: ignore[index]
    assert isinstance(ef, EpisodeFile)
    assert ef.size == 1_500_000_000


@pytest.mark.anyio
async def test_sonarr_delete_episode_file_sends_delete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    client = _sonarr({"/api/v3/episodefile/99": (200, {})})
    with caplog.at_level(logging.INFO, logger="arr_mcp.services.sonarr"):
        result = await client.delete_episode_file(99)
    assert result.ok
    assert "99" in caplog.text


@pytest.mark.anyio
async def test_sonarr_error_propagates() -> None:
    client = _sonarr({"/api/v3/series": (503, {"error": "Service Unavailable"})})
    result = await client.get_series()
    assert not result.ok
    assert result.status_code == 503


# ---------------------------------------------------------------------------
# RadarrClient
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_radarr_get_movies_returns_dataclasses() -> None:
    payload = [
        {
            "id": 1,
            "title": "Inception",
            "path": "/media/movies/Inception",
            "hasFile": True,
            "movieFileId": 42,
            "year": 2010,
            "status": "released",
            "monitored": False,
        }
    ]
    client = _radarr({"/api/v3/movie": (200, payload)})
    result = await client.get_movies()
    assert result.ok
    movie = result.data[0]  # type: ignore[index]
    assert isinstance(movie, Movie)
    assert movie.title == "Inception"
    assert movie.year == 2010
    assert movie.status == "released"
    assert movie.monitored is False
    assert movie.movie_file_id == 42


@pytest.mark.anyio
async def test_radarr_get_movie_files_returns_dataclasses() -> None:
    payload = [
        {
            "id": 42,
            "movieId": 1,
            "path": "/media/movies/Inception/Inception.mkv",
            "size": 8_000_000_000,
        }
    ]
    client = _radarr({"/api/v3/moviefile": (200, payload)})
    result = await client.get_movie_files()
    assert result.ok
    mf = result.data[0]  # type: ignore[index]
    assert isinstance(mf, MovieFile)
    assert mf.size == 8_000_000_000


@pytest.mark.anyio
async def test_radarr_delete_movie_file_sends_delete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    client = _radarr({"/api/v3/moviefile/42": (200, {})})
    with caplog.at_level(logging.INFO, logger="arr_mcp.services.radarr"):
        result = await client.delete_movie_file(42)
    assert result.ok
    assert "42" in caplog.text


@pytest.mark.anyio
async def test_radarr_error_propagates() -> None:
    client = _radarr({"/api/v3/movie": (401, {"error": "Unauthorized"})})
    result = await client.get_movies()
    assert not result.ok
    assert result.status_code == 401


# ---------------------------------------------------------------------------
# Registry integration — right client type returned
# ---------------------------------------------------------------------------


def test_registry_returns_sonarr_client(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from arr_mcp.services.registry import ServiceRegistry

    monkeypatch.setenv("SONARR_API_KEY", "key")
    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("sonarr")
    assert isinstance(client, SonarrClient)


def test_registry_returns_radarr_client(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from arr_mcp.services.registry import ServiceRegistry

    monkeypatch.setenv("RADARR_API_KEY", "key")
    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("radarr")
    assert isinstance(client, RadarrClient)

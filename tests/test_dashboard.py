"""Tests for the dashboard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.server import create_app


def _make_app(settings: Settings, containers: list[dict] | None = None):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=containers or [])
    mock_client.socket_path = "unix:///run/user/1000/podman/podman.sock"
    with patch("arr_mcp.server.ContainerClient", return_value=mock_client):
        return create_app(settings)


@pytest.fixture
def public_settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        container_runtime="podman",
        log_level="debug",
        dashboard_public=True,
    )


@pytest.fixture
def private_settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        container_runtime="podman",
        log_level="debug",
        dashboard_public=False,
    )


async def test_dashboard_returns_200_public(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert r.status_code == 200


async def test_dashboard_returns_html(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert "text/html" in r.headers["content-type"]
    assert "arr-mcp" in r.text


async def test_dashboard_rejects_missing_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert r.status_code == 401


async def test_dashboard_accepts_valid_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert r.status_code == 200


async def test_dashboard_rejects_wrong_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=wrong")
    assert r.status_code == 401


async def test_api_status_returns_200(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.status_code == 200


async def test_api_status_shape(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    data = r.json()
    assert "generated_at" in data
    assert "containers" in data
    assert "stacks" in data
    assert "disk" in data
    assert "runtime" in data


async def test_api_status_disk_fields(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    data = r.json()
    if data["disk"]:
        d = data["disk"][0]
        assert "total_gb" in d
        assert "used_gb" in d
        assert "free_gb" in d
        assert "used_pct" in d


async def test_dashboard_shows_containers(public_settings: Settings) -> None:
    containers = [
        {
            "Id": "abc123def456",
            "Names": ["/plex"],
            "Image": "linuxserver/plex:latest",
            "State": "running",
            "Status": "Up 2 hours",
        }
    ]
    app = _make_app(public_settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert "plex" in r.text


async def test_stacks_absent_for_non_compose_runtime(tmp_path) -> None:
    """Stacks section must be empty when runtime is not docker-compose."""
    media = tmp_path / "media"
    media.mkdir()
    settings = Settings(
        api_key="test-key",
        port=8081,
        media_dir=str(media),
        container_runtime="podman",
        dashboard_public=True,
    )
    containers = [
        {
            "Id": "abc123",
            "Names": ["/sonarr"],
            "Image": "linuxserver/sonarr",
            "State": "running",
            "Status": "Up 1 hour",
        }
    ]
    app = _make_app(settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.json()["stacks"] == []


async def test_stacks_present_for_compose_runtime(tmp_path) -> None:
    """Stacks section must be populated when runtime is docker-compose."""
    compose = tmp_path / "compose"
    compose.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    settings = Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(compose),
        media_dir=str(media),
        container_runtime="docker-compose",
        dashboard_public=True,
    )
    containers = [
        {
            "Id": "abc123",
            "Names": ["/sonarr"],
            "Image": "linuxserver/sonarr",
            "State": "running",
            "Status": "Up 1 hour",
        }
    ]
    app = _make_app(settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert len(r.json()["stacks"]) > 0

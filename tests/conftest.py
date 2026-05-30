"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.server import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media-server"
    media.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        stacks_dir=str(stacks),
        media_dir=str(media),
        container_runtime="podman",
        log_level="debug",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=[])
    client.post = AsyncMock(return_value={})
    client.delete = AsyncMock(return_value={})
    client.socket_path = "unix:///run/user/1000/podman/podman.sock"
    return client


@pytest.fixture
def app(settings: Settings, mock_client: MagicMock):
    with patch("arr_mcp.server.ContainerClient", return_value=mock_client):
        yield create_app(settings)


@pytest.fixture
async def http_client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

"""Shared fixtures for e2e tests.

Each test is parametrized over the three supported runtime configurations:
  - docker      (Docker Engine socket)
  - podman      (Podman rootless socket)
  - auto        (auto-detection, resolves to the fake socket path)

The ``FakeDockerTransport`` is injected at the httpx-transport level so no
real daemon is needed.  ``container_logs`` creates its own httpx client
inside the tool, so we also patch ``httpx.AsyncHTTPTransport`` in that
module to return the same fake transport.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.server import build_mcp_server, create_app

from .fake_docker_api import FakeDockerTransport

_FAKE_SOCK = "unix:///fake/docker.sock"

# ------------------------------------------------------------------
# Runtime parametrization
# ------------------------------------------------------------------

_RUNTIMES = [
    pytest.param("docker-compose", id="docker-compose"),
    pytest.param("docker", id="docker"),
    pytest.param("podman", id="podman"),
    pytest.param("auto", id="auto"),
]


@pytest.fixture(params=_RUNTIMES)
def runtime(request: pytest.FixtureRequest) -> str:
    return str(request.param)


# ------------------------------------------------------------------
# Core fixtures
# ------------------------------------------------------------------


@pytest.fixture
def fake_docker() -> FakeDockerTransport:
    """Fresh fake Docker transport for each test."""
    return FakeDockerTransport()


@pytest.fixture
def e2e_settings(tmp_path: Path, runtime: str) -> Settings:
    """Settings wired to tmp dirs and the fake socket, for every runtime."""
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="e2e-test-key",
        port=8082,
        compose_dir=str(stacks),
        services_dir=str(services),
        media_dir=str(media),
        container_runtime=runtime,
        socket_path=_FAKE_SOCK,
        log_level="debug",
    )


@pytest.fixture
def e2e_client(e2e_settings: Settings, fake_docker: FakeDockerTransport) -> ContainerClient:
    """ContainerClient whose httpx transport is the in-process fake."""
    with patch(
        "arr_mcp.runtime.detector.detect_runtime",
        return_value=(e2e_settings.container_runtime, _FAKE_SOCK),
    ):
        client = ContainerClient(e2e_settings)

    # Replace the live httpx client with one backed by the fake transport.
    client._client = httpx.AsyncClient(
        transport=fake_docker,
        base_url="http://localhost",
        timeout=5.0,
    )
    client.socket_path = _FAKE_SOCK
    return client


@pytest.fixture
def mcp(e2e_settings: Settings, e2e_client: ContainerClient, fake_docker: FakeDockerTransport):
    """FastMCP server wired to the fake Docker backend.

    Also patches ``httpx.AsyncHTTPTransport`` inside the containers module so
    that ``container_logs`` (which opens its own transport) uses the fake too.
    """
    server = build_mcp_server(e2e_settings, e2e_client)

    class _FakeTransportFactory(httpx.AsyncBaseTransport):
        """Replaces httpx.AsyncHTTPTransport(uds=...) inside container_logs."""

        def __init__(self, **_: object) -> None:
            pass

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return await fake_docker.handle_async_request(request)

    with patch("arr_mcp.tools.containers.httpx.AsyncHTTPTransport", _FakeTransportFactory):
        yield server


# ------------------------------------------------------------------
# HTTP-level fixture (auth / adversarial tests)
# ------------------------------------------------------------------


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    """Settings for HTTP-level tests — runtime config is irrelevant here."""
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="http-test-key",
        compose_dir=str(stacks),
        services_dir=str(services),
        media_dir=str(media),
        container_runtime="docker",
        socket_path=_FAKE_SOCK,
        log_level="debug",
    )


@pytest.fixture
def mock_container_client() -> MagicMock:
    c = MagicMock()
    c.get = AsyncMock(return_value=[])
    c.post = AsyncMock(return_value={})
    c.delete = AsyncMock(return_value={})
    c.socket_path = _FAKE_SOCK
    return c


@pytest.fixture
def http_app(app_settings: Settings, mock_container_client: MagicMock):
    with patch("arr_mcp.server.ContainerClient", return_value=mock_container_client):
        yield create_app(app_settings)


@pytest.fixture
async def http_client(http_app) -> httpx.AsyncClient:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app),
        base_url="http://test",
    ) as c:
        yield c

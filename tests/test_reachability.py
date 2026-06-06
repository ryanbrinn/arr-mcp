"""Tests for service API reachability and inter-service checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arr_mcp.services.base import ApiResult
from arr_mcp.tools.reachability import _extract_download_client_url

# ---------------------------------------------------------------------------
# _extract_download_client_url
# ---------------------------------------------------------------------------


def test_extract_url_http() -> None:
    settings = {"host": "sabnzbd", "port": 8080, "useSsl": False, "urlBase": ""}
    url = _extract_download_client_url("Sabnzbd", settings)
    assert url == "http://sabnzbd:8080"


def test_extract_url_https() -> None:
    settings = {"host": "sabnzbd", "port": 443, "useSsl": True, "urlBase": ""}
    url = _extract_download_client_url("Sabnzbd", settings)
    assert url == "https://sabnzbd:443"


def test_extract_url_with_urlbase() -> None:
    settings = {"host": "sabnzbd", "port": 8080, "useSsl": False, "urlBase": "/sabnzbd"}
    url = _extract_download_client_url("Sabnzbd", settings)
    assert url == "http://sabnzbd:8080/sabnzbd"


def test_extract_url_missing_host_returns_none() -> None:
    settings = {"port": 8080}
    url = _extract_download_client_url("Sabnzbd", settings)
    assert url is None


def test_extract_url_missing_port_returns_none() -> None:
    settings = {"host": "sabnzbd"}
    url = _extract_download_client_url("Sabnzbd", settings)
    assert url is None


# ---------------------------------------------------------------------------
# service_api_reachability — MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_service_api_reachability_no_credentials(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    mock_reg = MagicMock()
    mock_reg.available.return_value = []

    with patch("arr_mcp.tools.reachability.ServiceRegistry", return_value=mock_reg):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "service_api_reachability"
    )
    result = await tool_fn.fn()
    assert "No service credentials" in result[0].text


@pytest.mark.anyio
async def test_service_api_reachability_returns_results(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    mock_client = MagicMock()
    mock_client._base_url = "http://sonarr:8989"
    mock_client.health = AsyncMock(return_value=ApiResult(ok=True, status_code=200))

    mock_reg = MagicMock()
    mock_reg.available.return_value = ["sonarr"]
    mock_reg.get_client.return_value = mock_client

    with patch("arr_mcp.tools.reachability.ServiceRegistry", return_value=mock_reg):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "service_api_reachability"
    )
    result = await tool_fn.fn()
    payload = json.loads(result[0].text)
    assert payload["summary"]["reachable"] == 1
    assert payload["services"][0]["name"] == "sonarr"
    assert payload["services"][0]["reachable"] is True
    assert payload["services"][0]["auth_ok"] is True


@pytest.mark.anyio
async def test_service_api_reachability_auth_failure(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    mock_client = MagicMock()
    mock_client._base_url = "http://sonarr:8989"
    mock_client.health = AsyncMock(
        return_value=ApiResult(ok=False, status_code=401, error="HTTP 401")
    )

    mock_reg = MagicMock()
    mock_reg.available.return_value = ["sonarr"]
    mock_reg.get_client.return_value = mock_client

    with patch("arr_mcp.tools.reachability.ServiceRegistry", return_value=mock_reg):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "service_api_reachability"
    )
    result = await tool_fn.fn()
    payload = json.loads(result[0].text)
    assert payload["services"][0]["auth_ok"] is False
    assert payload["services"][0]["reachable"] is False


# ---------------------------------------------------------------------------
# inter_service_reachability — MCP tool
# ---------------------------------------------------------------------------


def _write_db(db_path: Path, clients: list[tuple]) -> None:  # type: ignore[type-arg]
    """Create a minimal DownloadClients table for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE DownloadClients "
        "(Id INTEGER PRIMARY KEY, Name TEXT, Implementation TEXT, Settings TEXT, Enable INTEGER)"
    )
    for row in clients:
        conn.execute("INSERT INTO DownloadClients VALUES (?,?,?,?,?)", row)
    conn.commit()
    conn.close()


@pytest.mark.anyio
async def test_inter_service_reachability_no_dbs(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    with patch("arr_mcp.tools.reachability.ServiceRegistry"):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "inter_service_reachability"
    )
    result = await tool_fn.fn()
    assert "No download client" in result[0].text


@pytest.mark.anyio
async def test_inter_service_reachability_checks_configured_clients(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    # Set up a sonarr directory with a database containing a download client
    sonarr_dir = tmp_path / "sonarr"
    sonarr_dir.mkdir()
    dc_settings = json.dumps(
        {"host": "sabnzbd", "port": 8080, "useSsl": False, "urlBase": "", "apiKey": "sab-key"}
    )
    _write_db(sonarr_dir / "sonarr.db", [(1, "SABnzbd", "Sabnzbd", dc_settings, 1)])

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    with patch("arr_mcp.tools.reachability.ServiceRegistry"):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "inter_service_reachability"
    )

    # Mock the HTTP check so we don't need a live sabnzbd
    with patch(
        "arr_mcp.tools.reachability._check_url",
        new_callable=AsyncMock,
        return_value=(True, 200, None),
    ):
        result = await tool_fn.fn()

    payload = json.loads(result[0].text)
    assert payload["summary"]["total"] == 1
    assert payload["download_clients"][0]["arr_service"] == "sonarr"
    assert payload["download_clients"][0]["client_name"] == "SABnzbd"
    assert payload["download_clients"][0]["reachable"] is True


@pytest.mark.anyio
async def test_inter_service_reachability_skips_disabled_clients(tmp_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.reachability import register_reachability_tools

    sonarr_dir = tmp_path / "sonarr"
    sonarr_dir.mkdir()
    dc_settings = json.dumps({"host": "sabnzbd", "port": 8080, "useSsl": False, "urlBase": ""})
    # Enable=0 → disabled
    _write_db(sonarr_dir / "sonarr.db", [(1, "SABnzbd", "Sabnzbd", dc_settings, 0)])

    server = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))

    with patch("arr_mcp.tools.reachability.ServiceRegistry"):
        register_reachability_tools(server, settings)

    tool_fn = next(
        t for t in server._tool_manager._tools.values() if t.name == "inter_service_reachability"
    )
    result = await tool_fn.fn()
    assert "No download client" in result[0].text

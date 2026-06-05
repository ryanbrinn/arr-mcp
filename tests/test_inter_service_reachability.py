"""Tests for inter-service (sonarr/radarr → sabnzbd) reachability checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.diagnostics import (
    _extract_download_client_url,
    check_download_client_reachability,
    register_diagnostic_tools,
)
from arr_mcp.tools.services import DownloadClientRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sabnzbd_client(
    host: str = "sabnzbd",
    port: int = 8080,
    api_key: str = "testkey",
    enable: bool = True,
) -> DownloadClientRecord:
    return DownloadClientRecord(
        id=1,
        name="SABnzbd",
        implementation="Sabnzbd",
        settings={"host": host, "port": port, "apiKey": api_key, "urlBase": ""},
        enable=enable,
    )


def _make_db_with_client(
    path: Path,
    host: str = "sabnzbd",
    port: int = 8080,
    api_key: str = "testkey",
    enable: bool = True,
) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE DownloadClients "
            "(Id INTEGER PRIMARY KEY, Name TEXT, Implementation TEXT, "
            "Settings TEXT, Enable INTEGER)"
        )
        conn.execute(
            "CREATE TABLE Indexers "
            "(Id INTEGER PRIMARY KEY, Name TEXT, Implementation TEXT, Enable INTEGER)"
        )
        settings = json.dumps({"host": host, "port": port, "apiKey": api_key, "urlBase": ""})
        conn.execute(
            "INSERT INTO DownloadClients (Name, Implementation, Settings, Enable) VALUES (?,?,?,?)",
            ("SABnzbd", "Sabnzbd", settings, int(enable)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# _extract_download_client_url
# ---------------------------------------------------------------------------


def test_extract_url_basic() -> None:
    client = _make_sabnzbd_client()
    assert _extract_download_client_url(client) == "http://sabnzbd:8080"


def test_extract_url_ssl() -> None:
    client = DownloadClientRecord(
        id=1,
        name="SABnzbd",
        implementation="Sabnzbd",
        settings={"host": "sabnzbd", "port": 9090, "useSsl": True},
        enable=True,
    )
    assert _extract_download_client_url(client) == "https://sabnzbd:9090"


def test_extract_url_with_url_base() -> None:
    client = DownloadClientRecord(
        id=1,
        name="SABnzbd",
        implementation="Sabnzbd",
        settings={"host": "sabnzbd", "port": 8080, "urlBase": "/sabnzbd"},
        enable=True,
    )
    assert _extract_download_client_url(client) == "http://sabnzbd:8080/sabnzbd"


def test_extract_url_missing_host() -> None:
    client = DownloadClientRecord(
        id=1, name="bad", implementation="Sabnzbd", settings={"port": 8080}, enable=True
    )
    assert _extract_download_client_url(client) is None


# ---------------------------------------------------------------------------
# check_download_client_reachability
# ---------------------------------------------------------------------------


async def test_check_reachability_success() -> None:
    client = _make_sabnzbd_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        reachable, code, error = await check_download_client_reachability(client)

    assert reachable is True
    assert code == 200
    assert error is None


async def test_check_reachability_connection_refused() -> None:
    client = _make_sabnzbd_client()

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        reachable, code, error = await check_download_client_reachability(client)

    assert reachable is False
    assert error == "connection refused"


async def test_check_reachability_timeout() -> None:
    client = _make_sabnzbd_client()

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        reachable, code, error = await check_download_client_reachability(client)

    assert reachable is False
    assert error == "timeout"


async def test_check_reachability_401_is_reachable() -> None:
    client = _make_sabnzbd_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        reachable, code, error = await check_download_client_reachability(client)

    assert reachable is True
    assert code == 401


async def test_check_reachability_missing_host() -> None:
    client = DownloadClientRecord(
        id=1, name="bad", implementation="Sabnzbd", settings={}, enable=True
    )
    reachable, code, error = await check_download_client_reachability(client)
    assert reachable is False
    assert "host" in (error or "")


# ---------------------------------------------------------------------------
# service_diagnose integration
# ---------------------------------------------------------------------------


@pytest.fixture
def server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    return s


async def test_service_diagnose_reports_reachable_download_client(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    _make_db_with_client(svc_dir / "sonarr.db")

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_resp)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        result = await server.call_tool(
            "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
        )

    data = json.loads(result[0][0].text)
    assert any("SABnzbd" in msg for msg in data["ok"])


async def test_service_diagnose_unreachable_download_client_is_critical(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    _make_db_with_client(svc_dir / "sonarr.db")

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = http

        result = await server.call_tool(
            "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
        )

    data = json.loads(result[0][0].text)
    assert data["status"] == "critical"
    assert any(i["category"] == "inter-service" for i in data["issues"])


async def test_service_diagnose_no_db_skips_inter_service(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    # No DB file — inter-service check should be skipped entirely

    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert not any(i["category"] == "inter-service" for i in data["issues"])
    assert not any(w["category"] == "inter-service" for w in data["warnings"])


async def test_service_diagnose_disabled_client_skipped_for_reachability(
    server: FastMCP, settings: Settings
) -> None:
    """Disabled download clients are already warned by run_diagnostics; skip reachability."""
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    _make_db_with_client(svc_dir / "sonarr.db", enable=False)

    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    # Should warn about disabled client from run_diagnostics, but no inter-service error
    assert not any(i["category"] == "inter-service" for i in data["issues"])

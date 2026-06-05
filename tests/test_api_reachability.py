"""Tests for service API reachability checks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.diagnostics import (
    _apply_api_findings,
    check_api_reachability,
    register_diagnostic_tools,
)
from arr_mcp.tools.services import (
    KNOWN_SERVICES,
    ApiReachabilityResult,
    DiagnosticReport,
    extract_ini_api_key,
    extract_service_port,
    extract_xml_api_key,
)

# ---------------------------------------------------------------------------
# extract_service_port
# ---------------------------------------------------------------------------


def test_extract_service_port_from_xml(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>9999</Port></Config>")
    info = KNOWN_SERVICES["sonarr"]
    assert extract_service_port(svc_dir, info) == 9999


def test_extract_service_port_falls_back_to_default(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    info = KNOWN_SERVICES["sonarr"]
    assert extract_service_port(svc_dir, info) == 8989


def test_extract_service_port_no_port_key_uses_default(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sabnzbd"
    svc_dir.mkdir()
    info = KNOWN_SERVICES["sabnzbd"]
    assert extract_service_port(svc_dir, info) == 8080


# ---------------------------------------------------------------------------
# extract_xml_api_key
# ---------------------------------------------------------------------------


def test_extract_xml_api_key_success(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>mykey123</ApiKey></Config>")
    assert extract_xml_api_key(svc_dir, KNOWN_SERVICES["sonarr"]) == "mykey123"


def test_extract_xml_api_key_missing_file(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    assert extract_xml_api_key(svc_dir, KNOWN_SERVICES["sonarr"]) == ""


def test_extract_xml_api_key_non_xml_service(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sabnzbd"
    svc_dir.mkdir()
    assert extract_xml_api_key(svc_dir, KNOWN_SERVICES["sabnzbd"]) == ""


# ---------------------------------------------------------------------------
# extract_ini_api_key
# ---------------------------------------------------------------------------


def test_extract_ini_api_key_sabnzbd(tmp_path: Path) -> None:

    svc_dir = tmp_path / "sabnzbd"
    svc_dir.mkdir()
    ini = "[misc]\napi_key = sabkey456\n"
    (svc_dir / "sabnzbd.ini").write_text(ini)
    assert extract_ini_api_key(svc_dir, KNOWN_SERVICES["sabnzbd"], "misc", "api_key") == "sabkey456"


def test_extract_ini_api_key_missing(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sabnzbd"
    svc_dir.mkdir()
    assert extract_ini_api_key(svc_dir, KNOWN_SERVICES["sabnzbd"], "misc", "api_key") == ""


# ---------------------------------------------------------------------------
# check_api_reachability — unit tests with mocked httpx
# ---------------------------------------------------------------------------


async def test_check_api_reachability_success(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_api_reachability("sonarr", svc_dir, KNOWN_SERVICES["sonarr"])

    assert result.reachable is True
    assert result.status_code == 200
    assert result.error is None


async def test_check_api_reachability_timeout(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_api_reachability("sonarr", svc_dir, KNOWN_SERVICES["sonarr"])

    assert result.reachable is False
    assert result.error == "timeout"


async def test_check_api_reachability_connection_refused(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_api_reachability("sonarr", svc_dir, KNOWN_SERVICES["sonarr"])

    assert result.reachable is False
    assert result.error == "connection refused"


async def test_check_api_reachability_401_counted_reachable(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_api_reachability("sonarr", svc_dir, KNOWN_SERVICES["sonarr"])

    assert result.reachable is True
    assert result.status_code == 401


async def test_check_api_reachability_500_unreachable(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("arr_mcp.tools.diagnostics.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_api_reachability("sonarr", svc_dir, KNOWN_SERVICES["sonarr"])

    assert result.reachable is False
    assert result.status_code == 500


async def test_check_api_reachability_no_health_path(tmp_path: Path) -> None:
    svc_dir = tmp_path / "nzbget"
    svc_dir.mkdir()
    result = await check_api_reachability("nzbget", svc_dir, KNOWN_SERVICES["nzbget"])
    assert result.error == "no health path"
    assert result.reachable is False


# ---------------------------------------------------------------------------
# _apply_api_findings
# ---------------------------------------------------------------------------


def _make_report(service: str = "sonarr") -> DiagnosticReport:
    return DiagnosticReport(service=service, service_dir="/tmp", status="healthy")


def test_apply_api_findings_reachable_adds_ok() -> None:
    report = _make_report()
    _apply_api_findings("sonarr", ApiReachabilityResult(True, 200, None), report)
    assert any("API reachable" in msg for msg in report.ok)
    assert report.status == "healthy"


def test_apply_api_findings_401_adds_warning() -> None:
    report = _make_report()
    _apply_api_findings("sonarr", ApiReachabilityResult(True, 401, None), report)
    assert any(w.category == "api" for w in report.warnings)
    assert report.status == "degraded"


def test_apply_api_findings_unreachable_adds_error() -> None:
    report = _make_report()
    _apply_api_findings("sonarr", ApiReachabilityResult(False, None, "connection refused"), report)
    assert any(i.category == "api" for i in report.issues)
    assert report.status == "critical"


def test_apply_api_findings_no_health_path_noop() -> None:
    report = _make_report()
    _apply_api_findings("nzbget", ApiReachabilityResult(False, None, "no health path"), report)
    assert report.ok == []
    assert report.issues == []
    assert report.status == "healthy"


# ---------------------------------------------------------------------------
# service_diagnose integration with API check
# ---------------------------------------------------------------------------


@pytest.fixture
def server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    return s


async def test_service_diagnose_api_reachable_in_report(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc123</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()

    mock_result = ApiReachabilityResult(reachable=True, status_code=200, error=None)
    with patch(
        "arr_mcp.tools.diagnostics.check_api_reachability",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await server.call_tool(
            "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
        )

    data = json.loads(result[0][0].text)
    assert data["status"] == "healthy"
    assert any("API reachable" in msg for msg in data["ok"])


async def test_service_diagnose_api_unreachable_marks_critical(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc123</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()

    mock_result = ApiReachabilityResult(
        reachable=False, status_code=None, error="connection refused"
    )
    with patch(
        "arr_mcp.tools.diagnostics.check_api_reachability",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await server.call_tool(
            "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
        )

    data = json.loads(result[0][0].text)
    assert data["status"] == "critical"
    assert any(i["category"] == "api" for i in data["issues"])


async def test_service_diagnose_api_401_marks_degraded(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc123</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()

    mock_result = ApiReachabilityResult(reachable=True, status_code=401, error=None)
    with patch(
        "arr_mcp.tools.diagnostics.check_api_reachability",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await server.call_tool(
            "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
        )

    data = json.loads(result[0][0].text)
    assert data["status"] == "degraded"
    assert any(w["category"] == "api" for w in data["warnings"])

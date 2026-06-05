"""Tests for the service diagnostic MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from arr_mcp.config import Settings
from arr_mcp.tools.diagnostics import _check_diagnostic_path, register_diagnostic_tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    return s


# ---------------------------------------------------------------------------
# _check_diagnostic_path
# ---------------------------------------------------------------------------


def test_diagnostic_path_allows_config_xml(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "sonarr" / "config.xml")
    result = _check_diagnostic_path(p, settings)
    assert result.name == "config.xml"


def test_diagnostic_path_blocks_db(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "sonarr" / "sonarr.db")
    with pytest.raises(PermissionError, match="database"):
        _check_diagnostic_path(p, settings)


def test_diagnostic_path_blocks_db_wal(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "sonarr" / "sonarr.db-wal")
    with pytest.raises(PermissionError, match="database"):
        _check_diagnostic_path(p, settings)


def test_diagnostic_path_blocks_outside_services_dir(settings: Settings) -> None:
    with pytest.raises(PermissionError, match="services_dir"):
        _check_diagnostic_path("/etc/passwd", settings)


def test_diagnostic_path_blocks_path_traversal(settings: Settings) -> None:
    evil = str(Path(settings.services_dir) / ".." / ".." / "etc" / "passwd")
    with pytest.raises(PermissionError):
        _check_diagnostic_path(evil, settings)


def test_diagnostic_path_blocks_media_dir(settings: Settings) -> None:
    p = str(Path(settings.media_dir) / "movies" / "inception")
    with pytest.raises(PermissionError, match="services_dir"):
        _check_diagnostic_path(p, settings)


# ---------------------------------------------------------------------------
# service_scan
# ---------------------------------------------------------------------------


async def test_service_scan_empty_services_dir(server: FastMCP) -> None:
    result = await server.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data == []


async def test_service_scan_known_service_detected(server: FastMCP, settings: Settings) -> None:
    (Path(settings.services_dir) / "sonarr").mkdir()
    result = await server.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert len(data) == 1
    assert data[0]["name"] == "sonarr"
    assert data[0]["known"] is True


async def test_service_scan_unknown_service(server: FastMCP, settings: Settings) -> None:
    (Path(settings.services_dir) / "mycustom-app").mkdir()
    result = await server.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data[0]["known"] is False


async def test_service_scan_has_config_true(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "radarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config/>")
    result = await server.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data[0]["has_config"] is True


async def test_service_scan_has_config_false_without_file(
    server: FastMCP, settings: Settings
) -> None:
    (Path(settings.services_dir) / "sonarr").mkdir()
    result = await server.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data[0]["has_config"] is False


async def test_service_scan_container_running_cross_reference(
    settings: Settings, mock_client: MagicMock
) -> None:
    mock_client.get = AsyncMock(
        return_value=[{"Names": ["/sonarr"], "Status": "running", "Ports": []}]
    )
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    (Path(settings.services_dir) / "sonarr").mkdir()

    result = await s.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data[0]["container_running"] is True


async def test_service_scan_container_prefix_match(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Container named 'media-sonarr' should match the 'sonarr' service directory."""
    mock_client.get = AsyncMock(
        return_value=[{"Names": ["/media-sonarr"], "Status": "running", "Ports": []}]
    )
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    (Path(settings.services_dir) / "sonarr").mkdir()

    result = await s.call_tool("service_scan", {})
    data = json.loads(result[0][0].text)
    assert data[0]["container_running"] is True


# ---------------------------------------------------------------------------
# service_diagnose
# ---------------------------------------------------------------------------


async def test_service_diagnose_missing_config(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "critical"
    assert any(i["category"] == "missing" for i in data["issues"])


async def test_service_diagnose_valid_sonarr_healthy(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text(
        "<Config><ApiKey>abc123def456</ApiKey><Port>8989</Port></Config>"
    )
    (svc_dir / "logs").mkdir()
    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "healthy"
    assert data["issues"] == []


async def test_service_diagnose_localhost_binding_degraded(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text(
        "<Config>"
        "<ApiKey>abc123</ApiKey>"
        "<Port>8989</Port>"
        "<BindAddress>127.0.0.1</BindAddress>"
        "</Config>"
    )
    (svc_dir / "logs").mkdir()
    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "degraded"
    assert any(w["category"] == "port" for w in data["warnings"])


async def test_service_diagnose_unknown_service(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "mycustom"
    svc_dir.mkdir()
    result = await server.call_tool(
        "service_diagnose", {"service": "mycustom", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "unknown"
    assert any(w["severity"] == "info" for w in data["warnings"])


async def test_service_diagnose_path_outside_services_dir_blocked(
    server: FastMCP,
) -> None:
    with pytest.raises(ToolError):
        await server.call_tool("service_diagnose", {"service": "sonarr", "service_dir": "/etc"})


async def test_service_diagnose_db_path_blocked(server: FastMCP, settings: Settings) -> None:
    db_path = str(Path(settings.services_dir) / "sonarr" / "sonarr.db")
    with pytest.raises(ToolError):
        await server.call_tool("service_diagnose", {"service": "sonarr", "service_dir": db_path})


async def test_service_diagnose_path_traversal_blocked(server: FastMCP, settings: Settings) -> None:
    evil = str(Path(settings.services_dir) / ".." / ".." / "etc")
    with pytest.raises(ToolError):
        await server.call_tool("service_diagnose", {"service": "sonarr", "service_dir": evil})


# ---------------------------------------------------------------------------
# service_health_report
# ---------------------------------------------------------------------------


async def test_service_health_report_empty(server: FastMCP) -> None:
    result = await server.call_tool("service_health_report", {})
    data = json.loads(result[0][0].text)
    assert "scanned_at" in data
    assert data["services"] == []
    assert data["summary"]["healthy"] == 0


async def test_service_health_report_aggregates_services(
    server: FastMCP, settings: Settings
) -> None:
    for name, port in [("sonarr", "8989"), ("radarr", "7878")]:
        svc_dir = Path(settings.services_dir) / name
        svc_dir.mkdir()
        (svc_dir / "config.xml").write_text(
            f"<Config><ApiKey>key{name}</ApiKey><Port>{port}</Port></Config>"
        )
        (svc_dir / "logs").mkdir()

    result = await server.call_tool("service_health_report", {})
    data = json.loads(result[0][0].text)
    assert len(data["services"]) == 2
    assert data["summary"]["healthy"] == 2


async def test_service_health_report_skips_unknown_services(
    server: FastMCP, settings: Settings
) -> None:
    (Path(settings.services_dir) / "mycustomapp").mkdir()
    result = await server.call_tool("service_health_report", {})
    data = json.loads(result[0][0].text)
    assert data["services"] == []


# ---------------------------------------------------------------------------
# service_fix
# ---------------------------------------------------------------------------


async def test_service_fix_requires_confirm(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    result = await server.call_tool(
        "service_fix",
        {
            "service": "sonarr",
            "service_dir": str(svc_dir),
            "fix_type": "update_config_xml",
            "params": {"key": "Port", "value": "8989"},
        },
    )
    assert "confirm=True" in result[0][0].text


async def test_service_fix_update_config_xml_success(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    result = await server.call_tool(
        "service_fix",
        {
            "service": "sonarr",
            "service_dir": str(svc_dir),
            "fix_type": "update_config_xml",
            "params": {"key": "Port", "value": "9090"},
            "confirm": True,
        },
    )
    data = json.loads(result[0][0].text)
    assert data["changed"] is True
    assert data["before"] == "8989"
    assert data["after"] == "9090"


async def test_service_fix_update_config_xml_key_not_found(
    server: FastMCP, settings: Settings
) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><Port>8989</Port></Config>")
    result = await server.call_tool(
        "service_fix",
        {
            "service": "sonarr",
            "service_dir": str(svc_dir),
            "fix_type": "update_config_xml",
            "params": {"key": "NonExistent", "value": "x"},
            "confirm": True,
        },
    )
    data = json.loads(result[0][0].text)
    assert data["changed"] is False


async def test_service_fix_unknown_fix_type_raises(server: FastMCP, settings: Settings) -> None:
    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    with pytest.raises(ToolError):
        await server.call_tool(
            "service_fix",
            {
                "service": "sonarr",
                "service_dir": str(svc_dir),
                "fix_type": "do_something_evil",
                "params": {},
                "confirm": True,
            },
        )


async def test_service_fix_update_env_var_no_compose_dir(
    server: FastMCP, settings: Settings
) -> None:
    # Override compose_dir to empty to simulate unconfigured state
    empty_settings = Settings(
        api_key="test-key",
        compose_dir="",
        services_dir=settings.services_dir,
        media_dir=settings.media_dir,
        container_runtime="docker",
    )
    s = FastMCP("test")
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=[])
    register_diagnostic_tools(s, empty_settings, mock_client)

    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    result = await s.call_tool(
        "service_fix",
        {
            "service": "sonarr",
            "service_dir": str(svc_dir),
            "fix_type": "update_env_var",
            "params": {"stack": "media", "var": "SONARR_API_KEY", "value": "new"},
            "confirm": True,
        },
    )
    assert "compose_dir" in result[0][0].text


async def test_service_fix_update_env_var_dict_format(server: FastMCP, settings: Settings) -> None:
    """update_env_var works when compose environment is a dict."""
    import yaml

    stack_dir = Path(settings.compose_dir) / "media"
    stack_dir.mkdir()
    compose = {
        "services": {
            "sonarr": {
                "image": "linuxserver/sonarr",
                "environment": {"SONARR_API_KEY": "old", "TZ": "UTC"},
            }
        }
    }
    (stack_dir / "compose.yaml").write_text(yaml.dump(compose))

    svc_dir = Path(settings.services_dir) / "sonarr"
    svc_dir.mkdir()
    result = await server.call_tool(
        "service_fix",
        {
            "service": "sonarr",
            "service_dir": str(svc_dir),
            "fix_type": "update_env_var",
            "params": {"stack": "media", "var": "SONARR_API_KEY", "value": "newkey"},
            "confirm": True,
        },
    )
    data = json.loads(result[0][0].text)
    assert data["changed"] is True
    assert data["before"] == "old"
    assert data["after"] == "newkey"

    # Verify the file was actually written
    written = yaml.safe_load((stack_dir / "compose.yaml").read_text())
    assert written["services"]["sonarr"]["environment"]["SONARR_API_KEY"] == "newkey"

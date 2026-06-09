"""Tests for log reading and searching tools."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.logs import _check_log_path, register_log_tools


@pytest.mark.skipif(sys.platform == "win32", reason="Linux path test")
def test_varlog_allowed() -> None:
    result = _check_log_path("/var/log/syslog")
    assert str(result) == "/var/log/syslog"


def test_disallowed_log_path() -> None:
    with pytest.raises(PermissionError):
        _check_log_path("/etc/shadow")


def test_log_traversal_blocked() -> None:
    with pytest.raises(PermissionError):
        _check_log_path("/var/log/../../etc/passwd")


def test_config_xml_blocked_outside_varlog(tmp_path: Path) -> None:
    config = tmp_path / "config.xml"
    config.touch()
    with pytest.raises(PermissionError, match="blocked"):
        _check_log_path(str(config), extra_roots=[tmp_path])


def test_sqlite_db_blocked_outside_varlog(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    db.touch()
    with pytest.raises(PermissionError, match="blocked"):
        _check_log_path(str(db), extra_roots=[tmp_path])


def test_db_wal_blocked_outside_varlog(tmp_path: Path) -> None:
    wal = tmp_path / "sonarr.db-wal"
    wal.touch()
    with pytest.raises(PermissionError, match="blocked"):
        _check_log_path(str(wal), extra_roots=[tmp_path])


@pytest.mark.skipif(sys.platform == "win32", reason="Linux path test")
def test_config_xml_under_varlog_allowed() -> None:
    # Inside /var/log the blocklist is not applied (system logs can have any name)
    result = _check_log_path("/var/log/config.xml")
    assert result.name == "config.xml"


async def test_log_read_missing_file(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    result = await server.call_tool(
        "log_read", {"path": str(Path(settings.compose_dir) / "missing.log")}
    )
    assert "not found" in result[0][0].text.lower()


async def test_log_read_services_dir(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    log_dir = Path(settings.services_dir) / "radarr" / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "radarr.txt"
    log_file.write_text("info started\nerror broken\n")
    result = await server.call_tool("log_read", {"path": str(log_file)})
    assert "broken" in result[0][0].text


async def test_log_read_returns_last_n_lines(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    log_file = Path(settings.compose_dir) / "test.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(1, 21)))
    result = await server.call_tool("log_read", {"path": str(log_file), "lines": 5})
    text = result[0][0].text
    assert "line 20" in text
    assert "line 16" in text
    assert "line 15" not in text


async def test_log_search_finds_matches(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    log_file = Path(settings.compose_dir) / "app.log"
    log_file.write_text(
        "INFO starting\nERROR something broke\nINFO running\nERROR disk full\n"
    )
    result = await server.call_tool(
        "log_search", {"path": str(log_file), "query": "error"}
    )
    text = result[0][0].text
    assert "something broke" in text
    assert "disk full" in text
    assert "starting" not in text


async def test_log_search_case_insensitive(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    log_file = Path(settings.compose_dir) / "app.log"
    log_file.write_text("ERROR big problem\nerror small problem\nINFO fine\n")
    result = await server.call_tool(
        "log_search", {"path": str(log_file), "query": "ERROR"}
    )
    text = result[0][0].text
    assert "big problem" in text
    assert "small problem" in text


async def test_log_search_missing_file(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_log_tools(server, settings)
    result = await server.call_tool(
        "log_search",
        {"path": str(Path(settings.compose_dir) / "nope.log"), "query": "error"},
    )
    assert "not found" in result[0][0].text.lower()

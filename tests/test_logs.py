"""Tests for log reading and searching tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from arr_mcp.config import Settings
from arr_mcp.tools.logs import _check_log_path, register_log_tools
from mcp.server import Server


def test_varlog_allowed() -> None:
    result = _check_log_path("/var/log/syslog")
    assert str(result) == "/var/log/syslog"


def test_disallowed_log_path() -> None:
    with pytest.raises(PermissionError):
        _check_log_path("/etc/shadow")


def test_log_traversal_blocked() -> None:
    with pytest.raises(PermissionError):
        _check_log_path("/var/log/../../etc/passwd")


async def test_log_read_missing_file(settings: Settings, mock_client: MagicMock) -> None:
    server = Server("test")
    register_log_tools(server, settings)
    result = await server.call_tool("log_read", {"path": str(Path(settings.stacks_dir) / "missing.log")})
    assert "not found" in result[0].text.lower()


async def test_log_read_returns_last_n_lines(settings: Settings, mock_client: MagicMock) -> None:
    server = Server("test")
    register_log_tools(server, settings)
    log_file = Path(settings.stacks_dir) / "test.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(1, 21)))
    result = await server.call_tool("log_read", {"path": str(log_file), "lines": 5})
    text = result[0].text
    assert "line 20" in text
    assert "line 16" in text
    assert "line 15" not in text


async def test_log_search_finds_matches(settings: Settings, mock_client: MagicMock) -> None:
    server = Server("test")
    register_log_tools(server, settings)
    log_file = Path(settings.stacks_dir) / "app.log"
    log_file.write_text("INFO starting\nERROR something broke\nINFO running\nERROR disk full\n")
    result = await server.call_tool("log_search", {"path": str(log_file), "query": "error"})
    text = result[0].text
    assert "something broke" in text
    assert "disk full" in text
    assert "starting" not in text


async def test_log_search_case_insensitive(settings: Settings, mock_client: MagicMock) -> None:
    server = Server("test")
    register_log_tools(server, settings)
    log_file = Path(settings.stacks_dir) / "app.log"
    log_file.write_text("ERROR big problem\nerror small problem\nINFO fine\n")
    result = await server.call_tool("log_search", {"path": str(log_file), "query": "ERROR"})
    text = result[0].text
    assert "big problem" in text
    assert "small problem" in text


async def test_log_search_missing_file(settings: Settings, mock_client: MagicMock) -> None:
    server = Server("test")
    register_log_tools(server, settings)
    result = await server.call_tool(
        "log_search",
        {"path": str(Path(settings.stacks_dir) / "nope.log"), "query": "error"},
    )
    assert "not found" in result[0].text.lower()

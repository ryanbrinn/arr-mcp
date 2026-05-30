"""Tests for filesystem tool path safety and operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from arr_mcp.config import Settings
from arr_mcp.tools.filesystem import _check_path, register_filesystem_tools


def test_allowed_media_path(settings: Settings) -> None:
    p = str(Path(settings.media_dir) / "plex" / "config")
    result = _check_path(p, settings)
    assert str(result).startswith(settings.media_dir)


def test_allowed_stacks_path(settings: Settings) -> None:
    p = str(Path(settings.stacks_dir) / "mystack" / "compose.yaml")
    result = _check_path(p, settings)
    assert str(result).startswith(settings.stacks_dir)


def test_path_traversal_blocked(settings: Settings) -> None:
    evil = str(Path(settings.media_dir) / ".." / ".." / "etc" / "passwd")
    with pytest.raises(PermissionError):
        _check_path(evil, settings)


def test_absolute_disallowed_path(settings: Settings) -> None:
    with pytest.raises(PermissionError):
        _check_path("/etc/passwd", settings)


def test_root_path_blocked(settings: Settings) -> None:
    with pytest.raises(PermissionError):
        _check_path("/", settings)


def test_proc_path_blocked(settings: Settings) -> None:
    with pytest.raises(PermissionError):
        _check_path("/proc/1/environ", settings)


async def test_file_write_and_read(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    target = str(Path(settings.stacks_dir) / "test.txt")
    await server.call_tool("file_write", {"path": target, "content": "hello world"})
    result = await server.call_tool("file_read", {"path": target})
    assert "hello world" in result[0].text


async def test_directory_list_empty(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    result = await server.call_tool("directory_list", {"path": settings.stacks_dir})
    assert result[0].text == "(empty)"


async def test_directory_list_with_entries(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    (Path(settings.stacks_dir) / "mystack").mkdir()
    (Path(settings.stacks_dir) / "readme.txt").write_text("hi")
    result = await server.call_tool("directory_list", {"path": settings.stacks_dir})
    assert "mystack" in result[0].text
    assert "readme.txt" in result[0].text


async def test_file_write_outside_allowed_fails(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    with pytest.raises(ToolError, match="not in allowed roots"):
        await server.call_tool("file_write", {"path": "/etc/evil.txt", "content": "bad"})

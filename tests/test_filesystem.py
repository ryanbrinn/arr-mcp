"""Tests for filesystem tool path safety and operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from arr_mcp.config import Settings
from arr_mcp.tools.filesystem import _check_path, register_filesystem_tools


def test_allowed_media_path(settings: Settings) -> None:
    p = str(Path(settings.media_dir) / "movies" / "Inception")
    result = _check_path(p, settings)
    assert str(result).startswith(settings.media_dir)


def test_allowed_stacks_path(settings: Settings) -> None:
    p = str(Path(settings.compose_dir) / "mystack" / "compose.yaml")
    result = _check_path(p, settings)
    assert str(result).startswith(settings.compose_dir)


def test_allowed_services_path(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "radarr" / "logs" / "radarr.txt")
    result = _check_path(p, settings)
    assert str(result).startswith(settings.services_dir)


def test_services_write_blocked(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "radarr" / "config.yaml")
    with pytest.raises(PermissionError, match="Write access is not permitted"):
        _check_path(p, settings, write=True)


def test_services_config_xml_blocked(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "radarr" / "config.xml")
    with pytest.raises(PermissionError, match="blocked"):
        _check_path(p, settings)


def test_services_db_blocked(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "radarr" / "radarr.db")
    with pytest.raises(PermissionError, match="blocked"):
        _check_path(p, settings)


def test_services_db_wal_blocked(settings: Settings) -> None:
    p = str(Path(settings.services_dir) / "radarr" / "radarr.db-wal")
    with pytest.raises(PermissionError, match="blocked"):
        _check_path(p, settings)


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
    target = str(Path(settings.compose_dir) / "test.txt")
    await server.call_tool("file_write", {"path": target, "content": "hello world"})
    result = await server.call_tool("file_read", {"path": target})
    assert "hello world" in result[0][0].text


async def test_directory_list_empty(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    result = await server.call_tool("directory_list", {"path": settings.compose_dir})
    assert result[0][0].text == "(empty)"


async def test_directory_list_with_entries(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    (Path(settings.compose_dir) / "mystack").mkdir()
    (Path(settings.compose_dir) / "readme.txt").write_text("hi")
    with patch("arr_mcp.tools.filesystem.is_owned_by_current_user", return_value=True):
        result = await server.call_tool(
            "directory_list", {"path": settings.compose_dir}
        )
    assert "mystack" in result[0][0].text
    assert "readme.txt" in result[0][0].text


async def test_file_write_outside_allowed_fails(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    with pytest.raises(ToolError, match="not in allowed roots"):
        await server.call_tool(
            "file_write", {"path": "/etc/evil.txt", "content": "bad"}
        )


async def test_file_delete_success(settings: Settings, mock_client: MagicMock) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    target = Path(settings.compose_dir) / "to-delete.txt"
    target.write_text("bye")
    with patch("arr_mcp.tools.filesystem.is_owned_by_current_user", return_value=True):
        result = await server.call_tool(
            "file_delete", {"path": str(target), "confirm": True}
        )
    assert "Deleted" in result[0][0].text
    assert not target.exists()


async def test_file_delete_requires_confirm(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    target = Path(settings.compose_dir) / "safe.txt"
    target.write_text("keep me")
    result = await server.call_tool("file_delete", {"path": str(target)})
    assert "confirm=True" in result[0][0].text
    assert target.exists()


async def test_file_delete_outside_allowed_root(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    with pytest.raises(ToolError, match="not in allowed roots"):
        await server.call_tool("file_delete", {"path": "/etc/passwd", "confirm": True})


async def test_file_delete_not_found(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    missing = str(Path(settings.compose_dir) / "ghost.txt")
    with patch("arr_mcp.tools.filesystem.is_owned_by_current_user", return_value=True):
        result = await server.call_tool(
            "file_delete", {"path": missing, "confirm": True}
        )
    assert "not found" in result[0][0].text.lower()


async def test_file_delete_directory_rejected(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    d = Path(settings.compose_dir) / "mydir"
    d.mkdir()
    with patch("arr_mcp.tools.filesystem.is_owned_by_current_user", return_value=True):
        result = await server.call_tool(
            "file_delete", {"path": str(d), "confirm": True}
        )
    assert "directory" in result[0][0].text.lower()
    assert d.exists()


async def test_file_delete_root_owned_rejected(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Regression: root-owned files must never be deleted."""
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    target = Path(settings.compose_dir) / "root-file.txt"
    target.write_text("owned by root")
    with patch("arr_mcp.tools.filesystem.is_owned_by_current_user", return_value=False):
        with pytest.raises(ToolError, match="not owned by current user"):
            await server.call_tool(
                "file_delete", {"path": str(target), "confirm": True}
            )
    assert target.exists()


async def test_directory_list_excludes_root_owned_in_stacks_dir(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Root-owned directories must be hidden when listing the stacks root."""
    server = FastMCP("test")
    register_filesystem_tools(server, settings)
    (Path(settings.compose_dir) / "my-stack").mkdir()
    (Path(settings.compose_dir) / "root-stack").mkdir()
    with patch(
        "arr_mcp.tools.filesystem.is_owned_by_current_user",
        side_effect=lambda p: p.name != "root-stack",
    ):
        result = await server.call_tool(
            "directory_list", {"path": settings.compose_dir}
        )
    assert "my-stack" in result[0][0].text
    assert "root-stack" not in result[0][0].text

"""Tests for stack management tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arr_mcp.config import Settings
from arr_mcp.tools.stacks import register_stack_tools
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError


def _make_server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    server = FastMCP("test")
    register_stack_tools(server, mock_client, settings)
    return server


async def test_stack_list_empty(settings: Settings, mock_client: MagicMock) -> None:
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_list", {})
    assert "No stacks found" in result[0].text


async def test_stack_list_returns_stack_names(settings: Settings, mock_client: MagicMock) -> None:
    (Path(settings.stacks_dir) / "media-server").mkdir()
    (Path(settings.stacks_dir) / "monitoring").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_list", {})
    assert "media-server" in result[0].text
    assert "monitoring" in result[0].text


async def test_stack_down_without_confirm_is_safe(settings: Settings, mock_client: MagicMock) -> None:
    (Path(settings.stacks_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_down", {"name": "mystack", "confirm": False})
    assert "confirm=True" in result[0].text


async def test_stack_down_default_is_safe(settings: Settings, mock_client: MagicMock) -> None:
    """stack_down must default to confirm=False so it never runs without explicit opt-in."""
    (Path(settings.stacks_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_down", {"name": "mystack"})
    assert "confirm=True" in result[0].text


async def test_stack_down_with_confirm_runs(settings: Settings, mock_client: MagicMock) -> None:
    (Path(settings.stacks_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks._compose", new=AsyncMock(return_value="done")):
        result = await server.call_tool("stack_down", {"name": "mystack", "confirm": True})
        assert "done" in result[0].text


async def test_stack_up_nonexistent_raises(settings: Settings, mock_client: MagicMock) -> None:
    server = _make_server(settings, mock_client)
    with pytest.raises(ToolError, match="Stack not found"):
        await server.call_tool("stack_up", {"name": "nonexistent"})


async def test_compose_read_returns_content(settings: Settings, mock_client: MagicMock) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
    server = _make_server(settings, mock_client)
    result = await server.call_tool("compose_read", {"stack": "mystack"})
    assert "nginx" in result[0].text


async def test_compose_read_no_file(settings: Settings, mock_client: MagicMock) -> None:
    (Path(settings.stacks_dir) / "empty-stack").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("compose_read", {"stack": "empty-stack"})
    assert "No compose file" in result[0].text

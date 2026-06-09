"""Tests for stack management tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from arr_mcp.config import Settings
from arr_mcp.tools.stacks import register_stack_tools


def _make_server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    server = FastMCP("test")
    register_stack_tools(server, mock_client, settings)
    return server


async def test_stack_list_empty(settings: Settings, mock_client: MagicMock) -> None:
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_list", {})
    assert "No stacks found" in result[0][0].text


async def test_stack_list_returns_stack_names(
    settings: Settings, mock_client: MagicMock
) -> None:
    (Path(settings.compose_dir) / "media-server").mkdir()
    (Path(settings.compose_dir) / "monitoring").mkdir()
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await server.call_tool("stack_list", {})
    assert "media-server" in result[0][0].text
    assert "monitoring" in result[0][0].text


async def test_stack_down_without_confirm_is_safe(
    settings: Settings, mock_client: MagicMock
) -> None:
    (Path(settings.compose_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_down", {"name": "mystack", "confirm": False})
    assert "confirm=True" in result[0][0].text


async def test_stack_down_default_is_safe(
    settings: Settings, mock_client: MagicMock
) -> None:
    """stack_down must default to confirm=False — never runs without explicit opt-in."""
    (Path(settings.compose_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    result = await server.call_tool("stack_down", {"name": "mystack"})
    assert "confirm=True" in result[0][0].text


async def test_stack_down_with_confirm_runs(
    settings: Settings, mock_client: MagicMock
) -> None:
    (Path(settings.compose_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    from arr_mcp.helper.client import HelperResponse

    with (
        patch(
            "arr_mcp.tools.stacks.HelperClient.call",
            new=AsyncMock(
                return_value=HelperResponse(ok=True, output="done", exit_code=0)
            ),
        ),
        patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True),
    ):
        result = await server.call_tool(
            "stack_down", {"name": "mystack", "confirm": True}
        )
        assert "done" in result[0][0].text


async def test_stack_tools_degrade_gracefully(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Stack tools return a helpful message when the helper is unavailable."""
    (Path(settings.compose_dir) / "mystack").mkdir()
    server = _make_server(settings, mock_client)
    from arr_mcp.helper.client import HelperUnavailableError

    with (
        patch(
            "arr_mcp.tools.stacks.HelperClient.call",
            side_effect=HelperUnavailableError("/run/arr-agent/arr-agent.sock"),
        ),
        patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True),
    ):
        result = await server.call_tool("stack_up", {"name": "mystack"})
    assert "arr-agent" in result[0][0].text


async def test_stack_up_nonexistent_raises(
    settings: Settings, mock_client: MagicMock
) -> None:
    server = _make_server(settings, mock_client)
    with pytest.raises(ToolError, match="Stack not found"):
        await server.call_tool("stack_up", {"name": "nonexistent"})


async def test_compose_read_returns_content(
    settings: Settings, mock_client: MagicMock
) -> None:
    stack_dir = Path(settings.compose_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await server.call_tool("compose_read", {"stack": "mystack"})
    assert "nginx" in result[0][0].text


async def test_compose_read_no_file(settings: Settings, mock_client: MagicMock) -> None:
    (Path(settings.compose_dir) / "empty-stack").mkdir()
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await server.call_tool("compose_read", {"stack": "empty-stack"})
    assert "No compose file" in result[0][0].text


async def test_stack_list_excludes_root_owned(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Root-owned directories must not appear in stack_list."""
    (Path(settings.compose_dir) / "my-stack").mkdir()
    (Path(settings.compose_dir) / "root-stack").mkdir()
    server = _make_server(settings, mock_client)
    with patch(
        "arr_mcp.tools.stacks.is_owned_by_current_user",
        side_effect=lambda p: p.name != "root-stack",
    ):
        result = await server.call_tool("stack_list", {})
    assert "my-stack" in result[0][0].text
    assert "root-stack" not in result[0][0].text


async def test_stack_path_rejects_root_owned(
    settings: Settings, mock_client: MagicMock
) -> None:
    """Directly accessing a root-owned stack must raise ToolError."""
    (Path(settings.compose_dir) / "root-stack").mkdir()
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=False):
        with pytest.raises(ToolError, match="Stack not found"):
            await server.call_tool("stack_up", {"name": "root-stack"})


async def test_stack_list_respects_allowlist(
    tmp_path: Path, mock_client: MagicMock
) -> None:
    """stack_list only shows allowed stacks when allowed_stacks is configured."""
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    (stacks / "media").mkdir()
    (stacks / "nginx").mkdir()
    settings = Settings(
        api_key="k",
        compose_dir=str(stacks),
        media_dir=str(tmp_path),
        allowed_stacks=["media"],
    )
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await server.call_tool("stack_list", {})
    assert "media" in result[0][0].text
    assert "nginx" not in result[0][0].text


async def test_stack_up_blocked_by_allowlist(
    tmp_path: Path, mock_client: MagicMock
) -> None:
    """stack_up raises for stacks not in the allowlist."""
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    (stacks / "nginx").mkdir()
    settings = Settings(
        api_key="k",
        compose_dir=str(stacks),
        media_dir=str(tmp_path),
        allowed_stacks=["media"],
    )
    server = _make_server(settings, mock_client)
    with pytest.raises(ToolError, match="not in the allowed stacks"):
        await server.call_tool("stack_up", {"name": "nginx"})


async def test_stack_allowlist_empty_allows_all(
    tmp_path: Path, mock_client: MagicMock
) -> None:
    """When allowed_stacks is empty all stacks are accessible."""
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    (stacks / "nginx").mkdir()
    settings = Settings(
        api_key="k",
        compose_dir=str(stacks),
        media_dir=str(tmp_path),
        allowed_stacks=[],
    )
    server = _make_server(settings, mock_client)
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await server.call_tool("stack_list", {})
    assert "nginx" in result[0][0].text


def test_allowed_stacks_parsed_from_comma_string() -> None:
    """ARR_MCP_ALLOWED_STACKS comma string is parsed into a list."""
    s = Settings(api_key="k", allowed_stacks="media,downloads, plex")  # type: ignore[arg-type]
    assert s.allowed_stacks == ["media", "downloads", "plex"]

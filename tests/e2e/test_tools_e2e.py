"""E2E tool tests — all 15 tools against a fake Docker backend.

Parametrized over docker / podman / auto runtime configs.  Each test
exercises a full call_tool() path: tool registration → arg validation →
Docker API call → response formatting.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp import FastMCP

from .fake_docker_api import FakeDockerTransport

# ---------------------------------------------------------------------------
# Container tools
# ---------------------------------------------------------------------------


async def test_container_list_returns_seeded_containers(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    result = await mcp.call_tool("container_list", {})
    text = result[0][0].text
    assert "plex" in text
    assert "sonarr" in text


async def test_container_list_shows_ports(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    result = await mcp.call_tool("container_list", {})
    assert "32400" in result[0][0].text


async def test_container_start_updates_state(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    fake_docker.containers["sonarr"].status = "stopped"
    await mcp.call_tool("container_start", {"name": "sonarr"})
    assert fake_docker.containers["sonarr"].status == "running"


async def test_container_start_returns_name(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    result = await mcp.call_tool("container_start", {"name": "plex"})
    assert "plex" in result[0][0].text


async def test_container_stop_updates_state(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    await mcp.call_tool("container_stop", {"name": "plex"})
    assert fake_docker.containers["plex"].status == "stopped"


async def test_container_restart_leaves_container_running(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    await mcp.call_tool("container_restart", {"name": "plex"})
    assert fake_docker.containers["plex"].status == "running"


async def test_container_remove_without_confirm_is_refused(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    result = await mcp.call_tool("container_remove", {"name": "plex"})
    assert "confirm=True" in result[0][0].text
    assert "plex" in fake_docker.containers  # not removed


async def test_container_remove_with_confirm_deletes(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    await mcp.call_tool("container_remove", {"name": "plex", "confirm": True})
    assert "plex" not in fake_docker.containers


async def test_container_logs_decodes_multiplex_stream(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    fake_docker.containers["plex"].logs = ["hello from plex\n", "second line\n"]
    result = await mcp.call_tool("container_logs", {"name": "plex", "lines": 50})
    text = result[0][0].text
    assert "hello from plex" in text
    assert "second line" in text


async def test_container_stats_shows_cpu_and_memory(
    mcp: FastMCP, fake_docker: FakeDockerTransport
) -> None:
    result = await mcp.call_tool("container_stats", {})
    text = result[0][0].text
    # Header row always present
    assert "CPU%" in text
    # At least one running container (plex) should appear
    assert "plex" in text
    assert "MB" in text


# ---------------------------------------------------------------------------
# Stack tools — filesystem-level (no real compose binary needed for read ops)
# ---------------------------------------------------------------------------


def _require_compose(e2e_settings) -> None:
    """Skip if the runtime doesn't support stack tools."""
    if not e2e_settings.is_compose:
        pytest.skip("stack tools only available for docker-compose runtime")


async def test_stack_list_shows_owned_stacks(
    mcp: FastMCP, e2e_settings, fake_docker: FakeDockerTransport
) -> None:
    _require_compose(e2e_settings)
    stacks_root = Path(e2e_settings.compose_dir)
    (stacks_root / "mystack").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await mcp.call_tool("stack_list", {})
    assert "mystack" in result[0][0].text


async def test_stack_list_empty(mcp: FastMCP, e2e_settings) -> None:
    _require_compose(e2e_settings)
    result = await mcp.call_tool("stack_list", {})
    assert "No stacks found" in result[0][0].text


async def test_stack_down_without_confirm_is_refused(
    mcp: FastMCP, e2e_settings
) -> None:
    _require_compose(e2e_settings)
    stacks_root = Path(e2e_settings.compose_dir)
    (stacks_root / "arr").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await mcp.call_tool("stack_down", {"name": "arr"})
    assert "confirm=True" in result[0][0].text


async def test_compose_read_returns_file_contents(mcp: FastMCP, e2e_settings) -> None:
    _require_compose(e2e_settings)
    stacks_root = Path(e2e_settings.compose_dir)
    stack_dir = stacks_root / "media"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(
        "services:\n  plex:\n    image: plexinc/pms-docker\n"
    )
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await mcp.call_tool("compose_read", {"stack": "media"})
    assert "plex" in result[0][0].text
    assert "plexinc" in result[0][0].text


async def test_compose_write_creates_file(mcp: FastMCP, e2e_settings) -> None:
    _require_compose(e2e_settings)
    stacks_root = Path(e2e_settings.compose_dir)
    stack_dir = stacks_root / "newstack"
    stack_dir.mkdir()
    content = "services:\n  sonarr:\n    image: linuxserver/sonarr\n"
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        await mcp.call_tool("compose_write", {"stack": "newstack", "content": content})
    written = (stack_dir / "compose.yaml").read_text()
    assert "sonarr" in written


# ---------------------------------------------------------------------------
# Filesystem tools
# ---------------------------------------------------------------------------


async def test_disk_usage_returns_stats(mcp: FastMCP, e2e_settings) -> None:
    result = await mcp.call_tool("disk_usage", {"path": e2e_settings.media_dir})
    text = result[0][0].text
    assert "Total" in text
    assert "Used" in text
    assert "Free" in text
    assert "GB" in text


async def test_directory_list_shows_entries(mcp: FastMCP, e2e_settings) -> None:
    media = Path(e2e_settings.media_dir)
    (media / "movies").mkdir()
    (media / "readme.txt").write_text("hi")
    result = await mcp.call_tool("directory_list", {"path": e2e_settings.media_dir})
    text = result[0][0].text
    assert "movies" in text
    assert "readme.txt" in text


async def test_file_write_then_read_roundtrip(mcp: FastMCP, e2e_settings) -> None:
    target = str(Path(e2e_settings.compose_dir) / "notes.txt")
    await mcp.call_tool("file_write", {"path": target, "content": "roundtrip check"})
    result = await mcp.call_tool("file_read", {"path": target})
    assert "roundtrip check" in result[0][0].text


# ---------------------------------------------------------------------------
# Log tools
# ---------------------------------------------------------------------------


async def test_log_read_returns_tail(mcp: FastMCP, e2e_settings) -> None:
    log_file = Path(e2e_settings.compose_dir) / "service.log"
    log_file.write_text("line1\nline2\nline3\n")
    result = await mcp.call_tool("log_read", {"path": str(log_file), "lines": 2})
    text = result[0][0].text
    assert "line2" in text
    assert "line3" in text


async def test_log_search_finds_matching_lines(mcp: FastMCP, e2e_settings) -> None:
    log_file = Path(e2e_settings.compose_dir) / "app.log"
    log_file.write_text("INFO startup ok\nERROR disk full\nINFO shutdown\n")
    result = await mcp.call_tool(
        "log_search", {"path": str(log_file), "query": "error"}
    )
    text = result[0][0].text
    assert "disk full" in text
    assert "startup" not in text


async def test_log_search_is_case_insensitive(mcp: FastMCP, e2e_settings) -> None:
    log_file = Path(e2e_settings.compose_dir) / "mixed.log"
    log_file.write_text("WARNING: low memory\nwarning: cpu spike\n")
    result = await mcp.call_tool(
        "log_search", {"path": str(log_file), "query": "WARNING"}
    )
    text = result[0][0].text
    assert "low memory" in text
    assert "cpu spike" in text

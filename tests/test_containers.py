"""Tests for container lifecycle tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from mcp.server.fastmcp import FastMCP

from arr_mcp.tools.containers import _decode_log_stream, register_container_tools


def _make_server(mock_client: MagicMock) -> FastMCP:
    server = FastMCP("test")
    register_container_tools(server, mock_client)
    return server


async def test_container_remove_without_confirm_is_safe(mock_client: MagicMock) -> None:
    server = _make_server(mock_client)
    result = await server.call_tool("container_remove", {"name": "plex", "confirm": False})
    assert "confirm=True" in result[0][0].text
    mock_client.delete.assert_not_called()


async def test_container_remove_default_is_safe(mock_client: MagicMock) -> None:
    server = _make_server(mock_client)
    result = await server.call_tool("container_remove", {"name": "plex"})
    assert "confirm=True" in result[0][0].text
    mock_client.delete.assert_not_called()


async def test_container_remove_with_confirm_calls_delete(mock_client: MagicMock) -> None:
    server = _make_server(mock_client)
    await server.call_tool("container_remove", {"name": "plex", "confirm": True})
    mock_client.delete.assert_called_once()
    assert "plex" in mock_client.delete.call_args[0][0]


async def test_container_list_empty(mock_client: MagicMock) -> None:
    mock_client.get = AsyncMock(return_value=[])
    server = _make_server(mock_client)
    result = await server.call_tool("container_list", {})
    assert "No containers" in result[0][0].text


async def test_container_list_formats_output(mock_client: MagicMock) -> None:
    mock_client.get = AsyncMock(
        return_value=[
            {
                "Names": ["/plex"],
                "Status": "Up 2 hours",
                "Ports": [{"PublicPort": 32400, "PrivatePort": 32400, "Type": "tcp"}],
            },
            {
                "Names": ["/sonarr"],
                "Status": "Up 1 hour",
                "Ports": [{"PublicPort": 8989, "PrivatePort": 8989, "Type": "tcp"}],
            },
        ]
    )
    server = _make_server(mock_client)
    result = await server.call_tool("container_list", {})
    text = result[0][0].text
    assert "plex" in text
    assert "sonarr" in text
    assert "32400" in text
    assert "8989" in text


async def test_container_start_calls_post(mock_client: MagicMock) -> None:
    server = _make_server(mock_client)
    await server.call_tool("container_start", {"name": "sonarr"})
    mock_client.post.assert_called_once()
    assert "sonarr" in mock_client.post.call_args[0][0]


async def test_container_stop_calls_post(mock_client: MagicMock) -> None:
    server = _make_server(mock_client)
    await server.call_tool("container_stop", {"name": "radarr"})
    mock_client.post.assert_called_once()
    assert "radarr" in mock_client.post.call_args[0][0]


# --- _decode_log_stream unit tests ---


def _make_frame(payload: bytes, stream: int = 1) -> bytes:
    """Build a single Docker/Podman multiplex log frame."""
    header = bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    return header + payload


def test_decode_log_stream_single_frame() -> None:
    raw = _make_frame(b"hello world\n")
    assert _decode_log_stream(raw) == "hello world\n"


def test_decode_log_stream_multiple_frames() -> None:
    raw = _make_frame(b"line one\n") + _make_frame(b"line two\n", stream=2)
    result = _decode_log_stream(raw)
    assert "line one\n" in result
    assert "line two\n" in result


def test_decode_log_stream_empty_bytes() -> None:
    assert _decode_log_stream(b"") == ""


def test_decode_log_stream_plain_text_fallback() -> None:
    """Non-framed responses (some Podman versions) must be returned as plain text."""
    plain = b"2024-01-01 sonarr started\n2024-01-01 ready\n"
    result = _decode_log_stream(plain)
    assert "sonarr started" in result

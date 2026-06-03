"""Tests for HelperClient graceful degradation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from arr_mcp.helper.client import (
    HelperClient,
    HelperUnavailableError,
    unavailable_message,
)


async def test_is_available_returns_false_when_socket_missing(tmp_path: Path) -> None:
    """is_available() returns False — not an exception — when socket doesn't exist."""
    client = HelperClient(str(tmp_path / "missing.sock"))
    result = await client.is_available()
    assert result is False


async def test_is_available_returns_false_on_connect_error(tmp_path: Path) -> None:
    """is_available() returns False when the socket exists but connection is refused."""
    sock = tmp_path / "helper.sock"
    sock.touch()
    client = HelperClient(str(sock))
    import httpx

    with patch.object(client._client, "post", side_effect=httpx.ConnectError("refused")):
        result = await client.is_available()
    assert result is False


async def test_call_raises_helper_unavailable_on_connect_error(tmp_path: Path) -> None:
    """call() raises HelperUnavailableError when the socket is unreachable."""
    sock = tmp_path / "helper.sock"
    sock.touch()
    client = HelperClient(str(sock))
    import httpx

    with patch.object(client._client, "post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(HelperUnavailableError):
            await client.call("quadlet_list")


async def test_unavailable_message_is_helpful() -> None:
    """unavailable_message() returns a non-empty string with setup guidance."""
    msg = unavailable_message()
    assert "arr-agent" in msg
    assert len(msg) > 20

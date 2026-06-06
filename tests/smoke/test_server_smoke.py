"""Smoke tests: real server process, HTTP surface verification.

These tests hit a live uvicorn process started from the installed wheel.
The server runs with ARR_MCP_SOCKET_PATH=/nonexistent-smoke.sock so that
detect_runtime() is bypassed.  Container tool calls would fail (no real
daemon), but all HTTP surface tests below stop short of invoking tools.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _mcp_request(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def _mcp_headers(api_key: str, session_id: str = "") -> dict[str, str]:
    """Headers required by the MCP streamable-HTTP transport."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_key}",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def _parse_sse_json(body: str) -> dict:
    """Extract the JSON object from an SSE data line."""
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise ValueError(f"No data: line found in SSE body:\n{body[:300]}")


def _mcp_initialize(base_url: str, api_key: str) -> str:
    """Run the MCP initialize handshake; return the session ID."""
    r = httpx.post(
        f"{base_url}/mcp",
        json=_mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        ),
        headers=_mcp_headers(api_key),
        timeout=10.0,
    )
    assert r.status_code == 200, f"initialize failed: {r.status_code} {r.text[:200]}"
    session_id = r.headers.get("mcp-session-id", "")
    assert session_id, "initialize response missing mcp-session-id header"
    return session_id


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(running_server: dict[str, str]) -> None:
    """GET /health returns 200 with status ok."""
    r = httpx.get(f"{running_server['url']}/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_loads(running_server: dict[str, str]) -> None:
    """GET / with valid API key returns HTML dashboard."""
    r = httpx.get(
        f"{running_server['url']}/",
        params={"key": running_server["api_key"]},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_dashboard_auth_required(running_server: dict[str, str]) -> None:
    """GET / without credentials returns 401."""
    r = httpx.get(f"{running_server['url']}/")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------


def test_api_status_auth_required(running_server: dict[str, str]) -> None:
    """GET /api/status without Authorization header returns 401."""
    r = httpx.get(f"{running_server['url']}/api/status")
    assert r.status_code == 401


def test_api_status_invalid_key(running_server: dict[str, str]) -> None:
    """GET /api/status with wrong key returns 401."""
    r = httpx.get(
        f"{running_server['url']}/api/status",
        params={"key": "wrong-key"},
    )
    assert r.status_code == 401


def test_api_status_valid_key(running_server: dict[str, str]) -> None:
    """GET /api/status with valid key returns 200 JSON."""
    r = httpx.get(
        f"{running_server['url']}/api/status",
        params={"key": running_server["api_key"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# /mcp endpoint — auth
# ---------------------------------------------------------------------------


def test_mcp_auth_required(running_server: dict[str, str]) -> None:
    """POST /mcp without Authorization returns 401."""
    r = httpx.post(
        f"{running_server['url']}/mcp",
        json=_mcp_request("tools/list"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    assert r.status_code == 401


def test_mcp_invalid_key_rejected(running_server: dict[str, str]) -> None:
    """POST /mcp with wrong key returns 401."""
    r = httpx.post(
        f"{running_server['url']}/mcp",
        json=_mcp_request("tools/list"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer bad-key",
        },
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /mcp endpoint — MCP protocol
# ---------------------------------------------------------------------------


def test_mcp_tools_list(running_server: dict[str, str]) -> None:
    """Authenticated tools/list returns a non-empty list of tools."""
    session_id = _mcp_initialize(running_server["url"], running_server["api_key"])

    r = httpx.post(
        f"{running_server['url']}/mcp",
        json=_mcp_request("tools/list"),
        headers=_mcp_headers(running_server["api_key"], session_id),
        timeout=10.0,
    )
    assert r.status_code == 200

    body = _parse_sse_json(r.text)
    tools = body.get("result", {}).get("tools", [])
    assert len(tools) > 0, "Expected at least one registered tool"

    tool_names = {t["name"] for t in tools}
    assert "container_list" in tool_names, f"container_list missing from tools: {tool_names}"


def test_mcp_tools_include_filesystem(running_server: dict[str, str]) -> None:
    """tools/list includes filesystem tools."""
    session_id = _mcp_initialize(running_server["url"], running_server["api_key"])

    r = httpx.post(
        f"{running_server['url']}/mcp",
        json=_mcp_request("tools/list"),
        headers=_mcp_headers(running_server["api_key"], session_id),
        timeout=10.0,
    )
    assert r.status_code == 200

    body = _parse_sse_json(r.text)
    tool_names = {t["name"] for t in body.get("result", {}).get("tools", [])}
    expected = {"disk_usage", "directory_list", "file_read", "file_write"}
    missing = expected - tool_names
    assert not missing, f"Filesystem tools missing: {missing}"

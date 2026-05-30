"""Tests for the health endpoint."""

from __future__ import annotations


async def test_health_returns_200(http_client) -> None:
    r = await http_client.get("/health")
    assert r.status_code == 200


async def test_health_returns_ok_status(http_client) -> None:
    r = await http_client.get("/health")
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "arr-mcp"


async def test_health_requires_no_auth(http_client) -> None:
    """Health endpoint must be reachable without a token."""
    r = await http_client.get("/health")
    assert r.status_code == 200

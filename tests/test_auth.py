"""Tests for the API key authentication middleware."""

from __future__ import annotations


async def test_no_auth_header_returns_401(http_client) -> None:
    r = await http_client.post("/mcp")
    assert r.status_code == 401


async def test_wrong_token_returns_401(http_client) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401


async def test_malformed_auth_no_bearer_prefix(http_client) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "test-key"})
    assert r.status_code == 401


async def test_empty_token_returns_401(http_client) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


async def test_correct_token_passes_auth(http_client) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer test-key"})
    assert r.status_code != 401


async def test_health_bypasses_auth(http_client) -> None:
    r = await http_client.get("/health")
    assert r.status_code == 200

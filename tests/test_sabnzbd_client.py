"""Tests for SabnzbdClient — query-param auth and health endpoint."""

from __future__ import annotations

import json

import httpx
import pytest

from arr_mcp.services.sabnzbd import SabnzbdClient


def _client(responses: dict[str, tuple[int, object]]) -> SabnzbdClient:
    def handler(req: httpx.Request) -> httpx.Response:
        # Match on path + query string so we can assert on apikey/mode params
        full = req.url.path + ("?" + str(req.url.query) if req.url.query else "")
        for key, (status, body) in responses.items():
            if full.startswith(key):
                return httpx.Response(
                    status,
                    content=json.dumps(body).encode(),
                    headers={"content-type": "application/json"},
                )
        return httpx.Response(403, content=b'{"error": "api key incorrect"}')

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SabnzbdClient("http://sabnzbd:8080", "testkey", http=http)


@pytest.mark.anyio
async def test_health_uses_query_param_auth() -> None:
    client = _client({"/api?": (200, {"version": "4.3.0"})})
    result = await client.health()

    assert result.ok
    assert result.status_code == 200


@pytest.mark.anyio
async def test_health_sends_mode_version() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200,
            content=json.dumps({"version": "4.3.0"}).encode(),
            headers={"content-type": "application/json"},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SabnzbdClient("http://sabnzbd:8080", "testkey", http=http)
    await client.health()

    assert len(captured) == 1
    req = captured[0]
    params = dict(req.url.params)
    assert params.get("apikey") == "testkey"
    assert params.get("mode") == "version"
    assert params.get("output") == "json"
    # Must NOT send X-Api-Key header (SABnzbd ignores it, but verify key is in params)
    assert req.url.path == "/api"


@pytest.mark.anyio
async def test_health_returns_not_ok_on_403() -> None:
    client = _client({})  # all paths fall through to 403
    result = await client.health()

    assert not result.ok
    assert result.status_code == 403


@pytest.mark.anyio
async def test_get_injects_apikey_automatically() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SabnzbdClient("http://sabnzbd:8080", "mykey", http=http)
    await client.get("/api", mode="queue")

    params = dict(captured[0].url.params)
    assert params["apikey"] == "mykey"
    assert params["output"] == "json"
    assert params["mode"] == "queue"


@pytest.mark.anyio
async def test_get_caller_apikey_not_overridden() -> None:
    """Explicit apikey from caller is preserved (not stomped by setdefault)."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SabnzbdClient("http://sabnzbd:8080", "mykey", http=http)
    await client.get("/api", apikey="override")

    params = dict(captured[0].url.params)
    assert params["apikey"] == "override"

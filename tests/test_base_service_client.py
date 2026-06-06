"""Tests for BaseServiceClient, ArrClient, and ServiceRegistry."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from arr_mcp.services.arr import ArrClient, HealthItem, QueueItem, SystemStatus, WantedMissing
from arr_mcp.services.base import BaseServiceClient, ServiceNotConfiguredError
from arr_mcp.services.credentials import CredentialStore, ServiceCredential
from arr_mcp.services.registry import ServiceRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_transport(responses: dict[str, tuple[int, object]]) -> httpx.MockTransport:
    """Build a MockTransport from {path: (status_code, body)} mapping."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in responses:
            status, body = responses[path]
            content = json.dumps(body).encode()
            return httpx.Response(
                status, content=content, headers={"content-type": "application/json"}
            )
        return httpx.Response(404, content=b'{"error":"not found"}')

    return httpx.MockTransport(handler)


def _client(responses: dict[str, tuple[int, object]]) -> BaseServiceClient:
    transport = _mock_transport(responses)
    http = httpx.AsyncClient(transport=transport)
    return BaseServiceClient("http://sonarr:8989", "test-key", http=http)


def _arr_client(responses: dict[str, tuple[int, object]]) -> ArrClient:
    transport = _mock_transport(responses)
    http = httpx.AsyncClient(transport=transport)
    return ArrClient("http://sonarr:8989", "test-key", http=http)


# ---------------------------------------------------------------------------
# BaseServiceClient — HTTP primitives
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_success() -> None:
    client = _client({"/api/test": (200, {"hello": "world"})})
    result = await client.get("/api/test")
    assert result.ok
    assert result.status_code == 200
    assert result.data == {"hello": "world"}


@pytest.mark.anyio
async def test_get_http_error_returns_ok_false() -> None:
    client = _client({"/api/test": (401, {"error": "Unauthorized"})})
    result = await client.get("/api/test")
    assert not result.ok
    assert result.status_code == 401
    assert result.error == "HTTP 401"


@pytest.mark.anyio
async def test_post_sends_json_body() -> None:
    received: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.content)
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BaseServiceClient("http://sonarr:8989", "key", http=http)
    result = await client.post("/api/v3/command", {"name": "RescanSeries"})
    assert result.ok
    assert json.loads(received[0]) == {"name": "RescanSeries"}


@pytest.mark.anyio
async def test_delete_success() -> None:
    client = _client({"/api/v3/queue/1": (200, {})})
    result = await client.delete("/api/v3/queue/1")
    assert result.ok


@pytest.mark.anyio
async def test_health_uses_health_path() -> None:
    client = _client({"/api/v3/system/status": (200, {"version": "4.0.0"})})
    result = await client.health()
    assert result.ok


@pytest.mark.anyio
async def test_api_key_sent_in_header() -> None:
    received_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers.append(request.headers)
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BaseServiceClient("http://sonarr:8989", "my-secret-key", http=http)
    await client.get("/api/v3/system/status")
    assert received_headers[0]["x-api-key"] == "my-secret-key"


# ---------------------------------------------------------------------------
# ArrClient — typed responses
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_system_status_returns_dataclass() -> None:
    client = _arr_client(
        {"/api/v3/system/status": (200, {"appName": "Sonarr", "version": "4.1.0"})}
    )
    result = await client.system_status()
    assert result.ok
    assert isinstance(result.data, SystemStatus)
    assert result.data.version == "4.1.0"
    assert result.data.app_name == "Sonarr"


@pytest.mark.anyio
async def test_get_queue_returns_dataclasses() -> None:
    queue_resp = {
        "records": [
            {
                "id": 1,
                "title": "Show S01E01",
                "status": "downloading",
                "trackedDownloadState": "downloading",
                "sizeLeft": 1024,
            }
        ]
    }
    client = _arr_client({"/api/v3/queue": (200, queue_resp)})
    result = await client.get_queue()
    assert result.ok
    assert isinstance(result.data, list)
    assert len(result.data) == 1  # type: ignore[arg-type]
    item = result.data[0]  # type: ignore[index]
    assert isinstance(item, QueueItem)
    assert item.title == "Show S01E01"


@pytest.mark.anyio
async def test_get_health_returns_dataclasses() -> None:
    health_resp = [
        {"source": "IndexerCheck", "type": "warning", "message": "No indexers", "wikiUrl": ""}
    ]
    client = _arr_client({"/api/v3/health": (200, health_resp)})
    result = await client.get_health()
    assert result.ok
    assert isinstance(result.data, list)
    item = result.data[0]  # type: ignore[index]
    assert isinstance(item, HealthItem)
    assert item.type == "warning"


@pytest.mark.anyio
async def test_get_wanted_missing_returns_dataclass() -> None:
    resp = {"totalRecords": 5, "records": [{"id": 1}]}
    client = _arr_client({"/api/v3/wanted/missing": (200, resp)})
    result = await client.get_wanted_missing()
    assert result.ok
    assert isinstance(result.data, WantedMissing)
    assert result.data.total_records == 5


@pytest.mark.anyio
async def test_arr_client_error_passthrough() -> None:
    client = _arr_client({"/api/v3/system/status": (403, {"error": "Forbidden"})})
    result = await client.system_status()
    assert not result.ok
    assert result.status_code == 403


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------


def test_registry_raises_when_no_credential(tmp_path: Path) -> None:
    registry = ServiceRegistry(str(tmp_path))
    with pytest.raises(ServiceNotConfiguredError, match="sonarr"):
        registry.get_client("sonarr")


def test_registry_raises_service_not_configured_not_key_error(tmp_path: Path) -> None:
    registry = ServiceRegistry(str(tmp_path))
    exc = None
    try:
        registry.get_client("sonarr")
    except ServiceNotConfiguredError as e:
        exc = e
    except KeyError:
        pytest.fail("Should raise ServiceNotConfiguredError, not KeyError")
    assert exc is not None


def test_registry_returns_arr_client_for_sonarr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONARR_API_KEY", "key")
    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("sonarr")
    assert isinstance(client, ArrClient)


def test_registry_returns_base_client_for_plex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLEX_TOKEN", "token")
    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("plex")
    assert isinstance(client, BaseServiceClient)
    assert not isinstance(client, ArrClient)


def test_registry_available_matches_credential_store(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set("radarr", ServiceCredential(api_key="key"))
    store.set("lidarr", ServiceCredential(api_key="key"))

    registry = ServiceRegistry(str(tmp_path))
    available = registry.available()
    assert "radarr" in available
    assert "lidarr" in available


def test_registry_uses_base_url_from_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="key", base_url="http://myhost:9999"))

    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("sonarr")
    assert client._base_url == "http://myhost:9999"


def test_registry_uses_port_from_xml_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>skey</ApiKey><Port>9191</Port></Config>")

    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("sonarr")
    assert "9191" in client._base_url


def test_registry_falls_back_to_default_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="key"))

    registry = ServiceRegistry(str(tmp_path))
    client = registry.get_client("sonarr")
    assert "8989" in client._base_url

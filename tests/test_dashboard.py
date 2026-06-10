"""Tests for the dashboard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.server import create_app


def _make_app(settings: Settings, containers: list[dict] | None = None):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=containers or [])
    mock_client.socket_path = "unix:///run/user/1000/podman/podman.sock"
    with patch("arr_mcp.server.ContainerClient", return_value=mock_client):
        return create_app(settings)


@pytest.fixture
def public_settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        container_runtime="podman",
        log_level="debug",
        dashboard_public=True,
    )


@pytest.fixture
def private_settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        container_runtime="podman",
        log_level="debug",
        dashboard_public=False,
    )


async def test_dashboard_returns_200_public(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert r.status_code == 200


async def test_dashboard_returns_html(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert "text/html" in r.headers["content-type"]
    assert "arr-mcp" in r.text


async def test_dashboard_redirects_unauthenticated(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_dashboard_accepts_valid_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert r.status_code == 200


async def test_dashboard_redirects_wrong_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/?key=wrong")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_api_status_returns_200(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.status_code == 200


async def test_api_status_shape(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    data = r.json()
    assert "generated_at" in data
    assert "containers" in data
    assert "stacks" in data
    assert "disk" in data
    assert "runtime" in data
    assert "alerts_recent" in data
    assert "upgrades" in data
    assert "connectivity" in data
    assert "stats" in data


async def test_api_status_stats_shape(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    stats = r.json()["stats"]
    assert "containers_running" in stats
    assert "containers_total" in stats
    assert "disk_max_pct" in stats
    assert "alerts_count" in stats
    assert "upgrades_count" in stats


async def test_api_status_alerts_empty_when_no_log(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.json()["alerts_recent"] == []


async def test_api_status_upgrades_empty_when_no_cache(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.json()["upgrades"] == []


async def test_api_status_connectivity_empty_when_no_credentials(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    # No services configured — connectivity list should be empty
    assert r.json()["connectivity"] == []


async def test_dashboard_tab_structure(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert 'id="infrastructure"' in r.text
    assert 'id="media"' in r.text
    assert 'data-tab="infrastructure"' in r.text
    assert 'data-tab="media"' in r.text


async def test_api_status_disk_fields(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    data = r.json()
    if data["disk"]:
        d = data["disk"][0]
        assert "total_gb" in d
        assert "used_gb" in d
        assert "free_gb" in d
        assert "used_pct" in d


async def test_dashboard_shows_containers(public_settings: Settings) -> None:
    containers = [
        {
            "Id": "abc123def456",
            "Names": ["/plex"],
            "Image": "linuxserver/plex:latest",
            "State": "running",
            "Status": "Up 2 hours",
        }
    ]
    app = _make_app(public_settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/")
    assert "plex" in r.text


async def test_stacks_absent_for_non_compose_runtime(tmp_path) -> None:
    """Stacks section must be empty when runtime is not docker-compose."""
    media = tmp_path / "media"
    media.mkdir()
    settings = Settings(
        api_key="test-key",
        port=8081,
        media_dir=str(media),
        container_runtime="podman",
        dashboard_public=True,
    )
    containers = [
        {
            "Id": "abc123",
            "Names": ["/sonarr"],
            "Image": "linuxserver/sonarr",
            "State": "running",
            "Status": "Up 1 hour",
        }
    ]
    app = _make_app(settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert r.json()["stacks"] == []


async def test_stacks_present_for_compose_runtime(tmp_path) -> None:
    """Stacks section must be populated when runtime is docker-compose."""
    compose = tmp_path / "compose"
    compose.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    settings = Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(compose),
        media_dir=str(media),
        container_runtime="docker-compose",
        dashboard_public=True,
    )
    containers = [
        {
            "Id": "abc123",
            "Names": ["/sonarr"],
            "Image": "linuxserver/sonarr",
            "State": "running",
            "Status": "Up 1 hour",
        }
    ]
    app = _make_app(settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status")
    assert len(r.json()["stacks"]) > 0


# ---------------------------------------------------------------------------
# POST /api/diagnose
# ---------------------------------------------------------------------------


async def test_api_diagnose_requires_issue_type(public_settings: Settings) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/api/diagnose", json={"context": {}})
    assert r.status_code == 400
    assert "issue_type" in r.json()["error"]


async def test_api_diagnose_rejects_missing_key(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose", json={"issue_type": "disk_pressure", "context": {}}
        )
    assert r.status_code == 401


async def test_api_diagnose_returns_fallback_when_null_provider(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose",
            json={
                "issue_type": "disk_pressure",
                "context": {"path": "/data", "used_pct": 92},
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert "remedies" in data
    assert len(data["remedies"]) > 0
    assert all("label" in rem and "tool" in rem for rem in data["remedies"])


async def test_api_diagnose_fallback_contains_known_tools(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose",
            json={
                "issue_type": "failed_download",
                "context": {"title": "Show S01E01", "error": "timeout"},
            },
        )
    data = r.json()
    tools = [rem["tool"] for rem in data["remedies"]]
    assert any("sonarr" in t or "sabnzbd" in t for t in tools)


async def test_api_diagnose_unknown_issue_type_returns_empty_remedies(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose",
            json={"issue_type": "totally_unknown", "context": {}},
        )
    assert r.status_code == 200
    data = r.json()
    assert "remedies" in data
    assert data["remedies"] == []


async def test_api_diagnose_with_ai_provider_returns_narrative(
    public_settings: Settings,
) -> None:
    """When AI provider returns a valid response, it is passed through."""
    mock_provider = MagicMock()
    mock_provider.complete_structured = AsyncMock(
        return_value={
            "narrative": "The disk is nearly full.",
            "remedies": [
                {"label": "Clean up", "tool": "watched_cleanup_preview", "args": {}}
            ],
        }
    )

    from arr_mcp.dashboard.routes import make_dashboard_routes
    from arr_mcp.runtime.client import ContainerClient

    mock_client = MagicMock(spec=ContainerClient)
    mock_client.get = AsyncMock(return_value=[])

    routes = make_dashboard_routes(mock_client, public_settings, mock_provider)

    async def _app(scope, receive, send):
        from starlette.applications import Starlette
        from starlette.routing import Route

        app = Starlette(
            routes=[
                Route(
                    "/api/diagnose", endpoint=routes["api_diagnose"], methods=["POST"]
                )
            ]
        )
        await app(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose",
            json={"issue_type": "disk_pressure", "context": {"used_pct": 95}},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["narrative"] == "The disk is nearly full."
    assert len(data["remedies"]) == 1


async def test_api_series_episodes_returns_404_when_unconfigured(
    public_settings: Settings,
) -> None:
    app = _make_app(public_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/series/1/episodes")
    assert r.status_code == 404


async def test_api_series_episodes_returns_episodes(public_settings: Settings) -> None:
    from arr_mcp.services.base import ApiResult
    from arr_mcp.services.models import Episode

    episodes = [
        Episode(
            id=2,
            series_id=1,
            season_number=1,
            episode_number=2,
            title="Second",
            has_file=True,
        ),
        Episode(
            id=1,
            series_id=1,
            season_number=1,
            episode_number=1,
            title="First",
            has_file=True,
        ),
        Episode(
            id=3,
            series_id=1,
            season_number=2,
            episode_number=1,
            title="Other Season",
            has_file=False,
        ),
    ]
    mock_sonarr = MagicMock()
    mock_sonarr.get_episodes = AsyncMock(return_value=ApiResult(ok=True, data=episodes))

    app = _make_app(public_settings)
    with patch(
        "arr_mcp.services.registry.ServiceRegistry.get_client",
        return_value=mock_sonarr,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/series/1/episodes?season=1")

    assert r.status_code == 200
    data = r.json()
    assert [e["episode_number"] for e in data["episodes"]] == [1, 2]
    assert data["episodes"][0]["title"] == "First"

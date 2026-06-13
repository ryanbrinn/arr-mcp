"""Tests for the dashboard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.dashboard.auth import AuthUser, SessionManager
from arr_mcp.server import create_app
from arr_mcp.services.users import UserStore


def _make_app(settings: Settings, containers: list[dict] | None = None):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=containers or [])
    mock_client.socket_path = "unix:///run/user/1000/podman/podman.sock"
    with patch("arr_mcp.server.ContainerClient", return_value=mock_client):
        return create_app(settings)


@pytest.fixture
def settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    s = Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        services_dir=str(services),
        container_runtime="podman",
        log_level="debug",
        session_secret="test-secret-32-bytes-long-abcdef",
    )
    # Seed an AppUser so the first-run setup redirect doesn't fire.
    UserStore(s.services_dir).create_local("setup-admin", "password123", is_admin=True)
    return s


@pytest.fixture
def unseeded_settings(tmp_path):
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    return Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(stacks),
        media_dir=str(media),
        services_dir=str(services),
        container_runtime="podman",
        log_level="debug",
        session_secret="test-secret-32-bytes-long-abcdef",
    )


def _signed_in_cookies(settings: Settings, is_admin: bool = False) -> dict[str, str]:
    user_store = UserStore(settings.services_dir)
    app_user = user_store.create_local("ryan", "password123", is_admin=is_admin)
    assert app_user is not None
    user = AuthUser(
        app_user_id=app_user.app_user_id,
        display_name="ryan",
        is_admin=is_admin,
    )
    token = SessionManager(settings.session_secret).sign(user)
    return {"arr_mcp_session": token}


async def test_dashboard_returns_200_with_key(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert r.status_code == 200


async def test_dashboard_returns_html(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert "text/html" in r.headers["content-type"]
    assert "arr-mcp" in r.text


async def test_dashboard_no_user_menu_when_anonymous(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert 'id="user-menu"' not in r.text


async def test_dashboard_shows_user_avatar_when_signed_in(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings),
    ) as client:
        r = await client.get("/")
    assert 'id="user-menu"' in r.text
    assert ">R</span>" in r.text
    assert "Sign out" in r.text
    assert "Pending review" not in r.text


async def test_dashboard_shows_admin_menu_item_when_admin(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings, is_admin=True),
    ) as client:
        r = await client.get("/")
    assert "Pending review" in r.text


async def test_dashboard_redirects_unauthenticated(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_dashboard_redirects_to_setup_when_no_users(
    unseeded_settings: Settings,
) -> None:
    app = _make_app(unseeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 302
    assert "/auth/setup" in r.headers["location"]


async def test_dashboard_accepts_valid_key(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert r.status_code == 200


async def test_dashboard_redirects_wrong_key(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/?key=wrong")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_api_status_returns_200(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    assert r.status_code == 200


async def test_api_status_shape(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
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


async def test_api_status_stats_shape(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    stats = r.json()["stats"]
    assert "containers_running" in stats
    assert "containers_total" in stats
    assert "disk_max_pct" in stats
    assert "alerts_count" in stats
    assert "upgrades_count" in stats


async def test_api_status_alerts_empty_when_no_log(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    assert r.json()["alerts_recent"] == []


async def test_api_status_upgrades_empty_when_no_cache(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    assert r.json()["upgrades"] == []


async def test_api_status_connectivity_empty_when_no_credentials(
    settings: Settings,
) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    # No services configured — connectivity list should be empty
    assert r.json()["connectivity"] == []


async def test_dashboard_tab_structure(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert 'id="infrastructure"' in r.text
    assert 'id="media"' in r.text
    assert 'data-tab="infrastructure"' in r.text
    assert 'data-tab="media"' in r.text


async def test_api_status_disk_fields(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/status?key=test-key")
    data = r.json()
    if data["disk"]:
        d = data["disk"][0]
        assert "total_gb" in d
        assert "used_gb" in d
        assert "free_gb" in d
        assert "used_pct" in d


async def test_dashboard_shows_containers(settings: Settings) -> None:
    containers = [
        {
            "Id": "abc123def456",
            "Names": ["/plex"],
            "Image": "linuxserver/plex:latest",
            "State": "running",
            "Status": "Up 2 hours",
        }
    ]
    app = _make_app(settings, containers=containers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/?key=test-key")
    assert "plex" in r.text


async def test_stacks_absent_for_non_compose_runtime(settings: Settings) -> None:
    """Stacks section must be empty when runtime is not docker-compose."""
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
        r = await client.get("/api/status?key=test-key")
    assert r.json()["stacks"] == []


async def test_stacks_present_for_compose_runtime(tmp_path) -> None:
    """Stacks section must be populated when runtime is docker-compose."""
    compose = tmp_path / "compose"
    compose.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    settings = Settings(
        api_key="test-key",
        port=8081,
        compose_dir=str(compose),
        media_dir=str(media),
        services_dir=str(services),
        container_runtime="docker-compose",
        session_secret="test-secret-32-bytes-long-abcdef",
    )
    UserStore(settings.services_dir).create_local(
        "setup-admin", "password123", is_admin=True
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
        r = await client.get("/api/status?key=test-key")
    assert len(r.json()["stacks"]) > 0


# ---------------------------------------------------------------------------
# POST /api/diagnose
# ---------------------------------------------------------------------------


async def test_api_diagnose_requires_issue_type(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/api/diagnose?key=test-key", json={"context": {}})
    assert r.status_code == 400
    assert "issue_type" in r.json()["error"]


async def test_api_diagnose_rejects_missing_key(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose", json={"issue_type": "disk_pressure", "context": {}}
        )
    assert r.status_code == 401


async def test_api_diagnose_returns_fallback_when_null_provider(
    settings: Settings,
) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose?key=test-key",
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


async def test_api_diagnose_fallback_contains_known_tools(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose?key=test-key",
            json={
                "issue_type": "failed_download",
                "context": {"title": "Show S01E01", "error": "timeout"},
            },
        )
    data = r.json()
    tools = [rem["tool"] for rem in data["remedies"]]
    assert any("sonarr" in t or "sabnzbd" in t for t in tools)


async def test_api_diagnose_unknown_issue_type_returns_empty_remedies(
    settings: Settings,
) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/diagnose?key=test-key",
            json={"issue_type": "totally_unknown", "context": {}},
        )
    assert r.status_code == 200
    data = r.json()
    assert "remedies" in data
    assert data["remedies"] == []


async def test_api_diagnose_with_ai_provider_returns_narrative(
    settings: Settings,
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

    routes = make_dashboard_routes(mock_client, settings, mock_provider)

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
            "/api/diagnose?key=test-key",
            json={"issue_type": "disk_pressure", "context": {"used_pct": 95}},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["narrative"] == "The disk is nearly full."
    assert len(data["remedies"]) == 1


# ---------------------------------------------------------------------------
# /api/interest
# ---------------------------------------------------------------------------


async def test_api_interest_requires_session(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/interest",
            json={"content_id": "100", "content_type": "movie", "state": "watched"},
        )
    assert r.status_code == 401


async def test_api_interest_invalid_json(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings),
    ) as client:
        r = await client.post(
            "/api/interest",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 400


async def test_api_interest_requires_content_id(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings),
    ) as client:
        r = await client.post(
            "/api/interest", json={"content_type": "movie", "state": "watched"}
        )
    assert r.status_code == 400


async def test_api_interest_rejects_invalid_content_type(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings),
    ) as client:
        r = await client.post(
            "/api/interest",
            json={"content_id": "100", "content_type": "song", "state": "watched"},
        )
    assert r.status_code == 400


async def test_api_interest_rejects_invalid_state(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=_signed_in_cookies(settings),
    ) as client:
        r = await client.post(
            "/api/interest",
            json={"content_id": "100", "content_type": "movie", "state": "bogus"},
        )
    assert r.status_code == 400


async def test_api_interest_sets_single_content_id(settings: Settings) -> None:
    from arr_mcp.services.interests import InterestState, InterestStore

    app = _make_app(settings)
    cookies = _signed_in_cookies(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
    ) as client:
        r = await client.post(
            "/api/interest",
            json={
                "content_id": "100",
                "content_type": "movie",
                "state": "marked_deletion",
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    user_store = UserStore(settings.services_dir)
    app_user = user_store.find_by_username("ryan")
    assert app_user is not None

    store = InterestStore(settings.services_dir)
    record = store.get("100", app_user.app_user_id)
    assert record.state == InterestState.marked_deletion
    assert record.username == "ryan"


async def test_api_interest_sets_multiple_content_ids(settings: Settings) -> None:
    from arr_mcp.services.interests import InterestState, InterestStore

    app = _make_app(settings)
    cookies = _signed_in_cookies(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
    ) as client:
        r = await client.post(
            "/api/interest",
            json={
                "content_ids": ["100", "101"],
                "content_type": "episode",
                "state": "watched",
            },
        )
    assert r.status_code == 200

    user_store = UserStore(settings.services_dir)
    app_user = user_store.find_by_username("ryan")
    assert app_user is not None

    store = InterestStore(settings.services_dir)
    assert store.get("100", app_user.app_user_id).state == InterestState.watched
    assert store.get("101", app_user.app_user_id).state == InterestState.watched

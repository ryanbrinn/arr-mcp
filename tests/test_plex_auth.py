"""Tests for Plex/local OAuth authentication, AppUser provisioning, and sessions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.requests import Request

from arr_mcp.config import Settings
from arr_mcp.dashboard.auth import (
    AuthUser,
    PlexPin,
    SessionManager,
    build_auth_user_plex,
    build_plex_auth_url,
    create_plex_pin,
    get_plex_user_info,
    is_local_request,
    needs_first_run_setup,
    poll_plex_pin,
)
from arr_mcp.server import create_app
from arr_mcp.services.users import UserStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
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
        session_secret="test-secret-32-bytes-long-abcdef",
        admin_users=["adminuser"],
    )


@pytest.fixture
def seeded_settings(settings: Settings) -> Settings:
    """Settings with one pre-existing AppUser, so first-run setup is closed."""
    UserStore(settings.services_dir).create_local(
        "setup-admin", "password123", is_admin=True
    )
    return settings


def _make_app(settings: Settings):
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=[])
    mock_client.socket_path = "unix:///run/user/1000/podman/podman.sock"
    with patch("arr_mcp.server.ContainerClient", return_value=mock_client):
        return create_app(settings)


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


def test_session_round_trip():
    sm = SessionManager("test-secret")
    user = AuthUser(
        app_user_id="abc-123",
        display_name="alice",
        is_admin=True,
        avatar_url="https://img",
        session_provider="plex",
    )
    token = sm.sign(user)
    result = sm.verify(token)
    assert result is not None
    assert result.app_user_id == "abc-123"
    assert result.display_name == "alice"
    assert result.is_admin is True
    assert result.avatar_url == "https://img"
    assert result.session_provider == "plex"


def test_session_rejects_tampered_token():
    sm = SessionManager("test-secret")
    user = AuthUser(app_user_id="abc-123", display_name="alice", is_admin=False)
    token = sm.sign(user)
    tampered = token[:-4] + "xxxx"
    assert sm.verify(tampered) is None


def test_session_rejects_wrong_secret():
    sm1 = SessionManager("secret-one")
    sm2 = SessionManager("secret-two")
    user = AuthUser(app_user_id="1", display_name="bob", is_admin=False)
    token = sm1.sign(user)
    assert sm2.verify(token) is None


def test_session_none_avatar_preserved():
    sm = SessionManager("test-secret")
    user = AuthUser(
        app_user_id="99", display_name="carol", is_admin=False, avatar_url=None
    )
    token = sm.sign(user)
    result = sm.verify(token)
    assert result is not None
    assert result.avatar_url is None


def test_session_rejects_legacy_token_without_uid():
    """Pre-#192 cookies (no 'uid' claim) must fail verification."""
    sm = SessionManager("test-secret")
    legacy = sm._s.dumps({"pid": "123", "usr": "alice", "adm": False, "ava": None})
    assert sm.verify(legacy) is None


# ---------------------------------------------------------------------------
# build_auth_user_plex
# ---------------------------------------------------------------------------


async def test_build_auth_user_plex_new_user_auto_provisions(
    seeded_settings: Settings,
) -> None:
    info = {"id": 42, "username": "newuser", "thumb": "https://avatar"}
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=False),
    ):
        user = await build_auth_user_plex(info, seeded_settings)

    assert user.display_name == "newuser"
    assert user.avatar_url == "https://avatar"
    assert user.is_admin is False
    assert user.session_provider == "plex"

    found = UserStore(seeded_settings.services_dir).find_by_linked_identity(
        "plex", "42"
    )
    assert found is not None
    assert found.app_user_id == user.app_user_id


async def test_build_auth_user_plex_existing_linked_user_reused(
    seeded_settings: Settings,
) -> None:
    store = UserStore(seeded_settings.services_dir)
    created = store.create_linked("plex", "42", "olduser", is_admin=False)

    info = {"id": 42, "username": "newname", "thumb": "https://new-avatar"}
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=False),
    ):
        user = await build_auth_user_plex(info, seeded_settings)

    assert user.app_user_id == created.app_user_id
    assert user.display_name == "newname"
    assert user.avatar_url == "https://new-avatar"


async def test_build_auth_user_plex_admin_via_home_user_flag(
    seeded_settings: Settings,
) -> None:
    info = {"id": 7, "username": "homeadmin"}
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=True),
    ):
        user = await build_auth_user_plex(info, seeded_settings)

    assert user.is_admin is True


async def test_build_auth_user_plex_admin_via_config(seeded_settings: Settings) -> None:
    info = {"id": 8, "username": "AdminUser"}  # matches admin_users=["adminuser"]
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=False),
    ):
        user = await build_auth_user_plex(info, seeded_settings)

    assert user.is_admin is True


async def test_build_auth_user_plex_first_appuser_forced_admin(
    settings: Settings,
) -> None:
    """The very first AppUser is always admin, even with no other signal."""
    info = {"id": 1, "username": "first"}
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=False),
    ):
        user = await build_auth_user_plex(info, settings)

    assert user.is_admin is True


async def test_build_auth_user_plex_admin_is_sticky(seeded_settings: Settings) -> None:
    """An existing admin AppUser is never auto-revoked on re-login."""
    store = UserStore(seeded_settings.services_dir)
    created = store.create_linked("plex", "55", "olduser", is_admin=True)
    assert created.is_admin is True

    info = {"id": 55, "username": "olduser"}
    with patch(
        "arr_mcp.dashboard.auth._detect_plex_home_admin",
        new=AsyncMock(return_value=False),
    ):
        user = await build_auth_user_plex(info, seeded_settings)

    assert user.is_admin is True


# ---------------------------------------------------------------------------
# build_plex_auth_url
# ---------------------------------------------------------------------------


def test_build_plex_auth_url_contains_code():
    pin = PlexPin(id="12345", code="abcdef12")
    url = build_plex_auth_url(
        pin, "http://localhost:8081/auth/plex/callback?pin_id=12345"
    )
    assert "app.plex.tv/auth" in url
    assert "code=abcdef12" in url
    assert "clientID=arr-mcp" in url


def test_build_plex_auth_url_contains_forward_url():
    pin = PlexPin(id="1", code="xyz")
    url = build_plex_auth_url(pin, "http://host/cb?pin_id=1")
    assert "forwardUrl" in url
    assert "pin_id" in url


# ---------------------------------------------------------------------------
# create_plex_pin
# ---------------------------------------------------------------------------


async def test_create_plex_pin_success():
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"id": 9999, "code": "testcode"}

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post = AsyncMock(return_value=mock_resp)

    pin = await create_plex_pin(http=mock_http)
    assert pin is not None
    assert pin.id == "9999"
    assert pin.code == "testcode"


async def test_create_plex_pin_http_error():
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 503

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post = AsyncMock(return_value=mock_resp)

    pin = await create_plex_pin(http=mock_http)
    assert pin is None


async def test_create_plex_pin_network_error():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    pin = await create_plex_pin(http=mock_http)
    assert pin is None


# ---------------------------------------------------------------------------
# poll_plex_pin
# ---------------------------------------------------------------------------


async def test_poll_plex_pin_claimed():
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"authToken": "mytoken123"}

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=mock_resp)

    token = await poll_plex_pin("9999", http=mock_http)
    assert token == "mytoken123"


async def test_poll_plex_pin_not_yet_claimed():
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"authToken": None}

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=mock_resp)

    token = await poll_plex_pin("9999", http=mock_http)
    assert token is None


async def test_poll_plex_pin_http_error():
    mock_resp = MagicMock()
    mock_resp.is_success = False

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=mock_resp)

    assert await poll_plex_pin("9999", http=mock_http) is None


# ---------------------------------------------------------------------------
# get_plex_user_info
# ---------------------------------------------------------------------------


async def test_get_plex_user_info_success():
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"id": 42, "username": "alice"}

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=mock_resp)

    info = await get_plex_user_info("token123", http=mock_http)
    assert info is not None
    assert info["username"] == "alice"


async def test_get_plex_user_info_http_failure():
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 401

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=mock_resp)

    assert await get_plex_user_info("badtoken", http=mock_http) is None


# ---------------------------------------------------------------------------
# needs_first_run_setup
# ---------------------------------------------------------------------------


def test_needs_first_run_setup_true_when_empty(settings: Settings) -> None:
    assert needs_first_run_setup(settings) is True


def test_needs_first_run_setup_false_when_seeded(seeded_settings: Settings) -> None:
    assert needs_first_run_setup(seeded_settings) is False


# ---------------------------------------------------------------------------
# is_local_request
# ---------------------------------------------------------------------------


def _make_request(scheme: str, host: str) -> Request:
    scope = {
        "type": "http",
        "scheme": scheme,
        "server": (host, 443 if scheme == "https" else 80),
        "headers": [],
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def test_is_local_request_true_for_http() -> None:
    assert is_local_request(_make_request("http", "192.168.1.50")) is True


def test_is_local_request_true_for_localhost_https() -> None:
    assert is_local_request(_make_request("https", "localhost")) is True


def test_is_local_request_true_for_private_ip_https() -> None:
    assert is_local_request(_make_request("https", "10.0.0.5")) is True


def test_is_local_request_false_for_public_https() -> None:
    assert is_local_request(_make_request("https", "arr.example.com")) is False


# ---------------------------------------------------------------------------
# Auth routes — sign-in page
# ---------------------------------------------------------------------------


async def test_auth_signin_returns_200(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/signin")
    assert r.status_code == 200
    assert "Sign in with Plex" in r.text


async def test_auth_signin_shows_error_param(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/signin?error=Something+went+wrong.")
    assert "Something went wrong." in r.text


async def test_auth_signin_shows_local_notice_over_http(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/signin")
    assert "may not finish on a local or non-HTTPS deployment" in r.text


async def test_auth_signin_redirects_to_setup_when_no_users(
    settings: Settings,
) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/signin")
    assert r.status_code == 302
    assert "/auth/setup" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/setup
# ---------------------------------------------------------------------------


async def test_auth_setup_returns_200_when_no_users(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/setup")
    assert r.status_code == 200
    assert "Create your admin account" in r.text or "Create admin account" in r.text


async def test_auth_setup_redirects_to_signin_when_users_exist(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/setup")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_setup_post_creates_first_admin(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/setup",
            data={
                "username": "alice",
                "password": "password123",
                "confirm_password": "password123",
            },
        )
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert "arr_mcp_session" in r.cookies

    user = UserStore(settings.services_dir).find_by_username("alice")
    assert user is not None
    assert user.is_admin is True


async def test_auth_setup_post_rejects_short_password(settings: Settings) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/setup",
            data={
                "username": "alice",
                "password": "short",
                "confirm_password": "short",
            },
        )
    assert r.status_code == 302
    assert "/auth/setup" in r.headers["location"]
    assert UserStore(settings.services_dir).has_any() is False


async def test_auth_setup_post_rejects_mismatched_passwords(
    settings: Settings,
) -> None:
    app = _make_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/setup",
            data={
                "username": "alice",
                "password": "password123",
                "confirm_password": "password456",
            },
        )
    assert r.status_code == 302
    assert "/auth/setup" in r.headers["location"]
    assert UserStore(settings.services_dir).has_any() is False


async def test_auth_setup_post_already_closed(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/setup",
            data={
                "username": "alice",
                "password": "password123",
                "confirm_password": "password123",
            },
        )
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/local/login
# ---------------------------------------------------------------------------


async def test_auth_local_login_success(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/local/login",
            data={"username": "setup-admin", "password": "password123"},
        )
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert "arr_mcp_session" in r.cookies


async def test_auth_local_login_wrong_password(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/local/login",
            data={"username": "setup-admin", "password": "wrongpassword"},
        )
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]
    assert "arr_mcp_session" not in r.cookies


async def test_auth_local_login_unknown_user(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post(
            "/auth/local/login",
            data={"username": "nosuchuser", "password": "password123"},
        )
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/plex/start
# ---------------------------------------------------------------------------


async def test_auth_plex_start_redirects_to_plex(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    with patch(
        "arr_mcp.dashboard.routes.create_plex_pin",
        new=AsyncMock(return_value=PlexPin(id="123", code="abcde")),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/plex/start")
    assert r.status_code == 302
    assert "app.plex.tv" in r.headers["location"]
    assert "abcde" in r.headers["location"]


async def test_auth_plex_start_handles_pin_failure(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    with patch(
        "arr_mcp.dashboard.routes.create_plex_pin",
        new=AsyncMock(return_value=None),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/plex/start")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/plex/callback
# ---------------------------------------------------------------------------


async def test_auth_plex_callback_sets_session_and_redirects(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    with (
        patch(
            "arr_mcp.dashboard.routes.poll_plex_pin",
            new=AsyncMock(return_value="auth-token-xyz"),
        ),
        patch(
            "arr_mcp.dashboard.routes.get_plex_user_info",
            new=AsyncMock(return_value={"id": 42, "username": "alice", "thumb": None}),
        ),
        patch(
            "arr_mcp.dashboard.auth._detect_plex_home_admin",
            new=AsyncMock(return_value=False),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/plex/callback?pin_id=123")
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert "arr_mcp_session" in r.cookies

    user = UserStore(seeded_settings.services_dir).find_by_linked_identity("plex", "42")
    assert user is not None
    assert user.display_name == "alice"


async def test_auth_plex_callback_missing_pin_id(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/plex/callback")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_plex_callback_pin_not_claimed(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    with patch(
        "arr_mcp.dashboard.routes.poll_plex_pin",
        new=AsyncMock(return_value=None),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/plex/callback?pin_id=123")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_plex_callback_user_info_failure(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    with (
        patch(
            "arr_mcp.dashboard.routes.poll_plex_pin",
            new=AsyncMock(return_value="some-token"),
        ),
        patch(
            "arr_mcp.dashboard.routes.get_plex_user_info",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/plex/callback?pin_id=123")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/link/plex/*
# ---------------------------------------------------------------------------


def _signed_in_cookies(settings: Settings, *, is_admin: bool = False) -> dict[str, str]:
    user_store = UserStore(settings.services_dir)
    app_user = user_store.create_local("ryan", "password123", is_admin=is_admin)
    assert app_user is not None
    user = AuthUser(
        app_user_id=app_user.app_user_id, display_name="ryan", is_admin=is_admin
    )
    token = SessionManager(settings.session_secret).sign(user)
    return {"arr_mcp_session": token}


async def test_auth_link_plex_landing_requires_session(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/link/plex")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_link_plex_landing_shows_notice_and_start_link(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    cookies = _signed_in_cookies(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/link/plex")
    assert r.status_code == 200
    assert "may not finish on a local or non-HTTPS deployment" in r.text
    assert "/auth/link/plex/start" in r.text


async def test_auth_link_plex_start_requires_session(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/link/plex/start")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_link_plex_start_redirects_to_plex(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    cookies = _signed_in_cookies(seeded_settings)
    with patch(
        "arr_mcp.dashboard.routes.create_plex_pin",
        new=AsyncMock(return_value=PlexPin(id="123", code="abcde")),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies=cookies,
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/link/plex/start")
    assert r.status_code == 302
    assert "app.plex.tv" in r.headers["location"]


async def test_auth_link_plex_callback_links_account(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    cookies = _signed_in_cookies(seeded_settings)
    user_store = UserStore(seeded_settings.services_dir)
    app_user = user_store.find_by_username("ryan")
    assert app_user is not None

    with (
        patch(
            "arr_mcp.dashboard.routes.poll_plex_pin",
            new=AsyncMock(return_value="auth-token-xyz"),
        ),
        patch(
            "arr_mcp.dashboard.routes.get_plex_user_info",
            new=AsyncMock(return_value={"id": 99, "username": "ryan", "thumb": None}),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies=cookies,
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/link/plex/callback?pin_id=123")
    assert r.status_code == 302
    assert r.headers["location"] == "/"

    updated = user_store.get(app_user.app_user_id)
    assert updated is not None
    assert updated.linked_identities.get("plex") == "99"


async def test_auth_link_plex_callback_conflict(seeded_settings: Settings) -> None:
    """Linking a Plex account already linked to a different AppUser fails."""
    app = _make_app(seeded_settings)
    user_store = UserStore(seeded_settings.services_dir)
    user_store.create_linked("plex", "99", "otheruser")

    cookies = _signed_in_cookies(seeded_settings)

    with (
        patch(
            "arr_mcp.dashboard.routes.poll_plex_pin",
            new=AsyncMock(return_value="auth-token-xyz"),
        ),
        patch(
            "arr_mcp.dashboard.routes.get_plex_user_info",
            new=AsyncMock(return_value={"id": 99, "username": "ryan", "thumb": None}),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies=cookies,
            follow_redirects=False,
        ) as client:
            r = await client.get("/auth/link/plex/callback?pin_id=123")
    assert r.status_code == 302
    assert "already+linked" in r.headers["location"]


# ---------------------------------------------------------------------------
# Auth routes — /auth/logout
# ---------------------------------------------------------------------------


async def test_auth_logout_clears_cookie(seeded_settings: Settings) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.post("/auth/logout")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


# ---------------------------------------------------------------------------
# Dashboard auth with session cookie
# ---------------------------------------------------------------------------


async def test_dashboard_accepts_valid_session_cookie(
    seeded_settings: Settings,
) -> None:
    cookies = _signed_in_cookies(seeded_settings)
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 200


async def test_dashboard_rejects_invalid_session_cookie(
    seeded_settings: Settings,
) -> None:
    app = _make_app(seeded_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"arr_mcp_session": "not-a-valid-token"},
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]

"""Tests for Plex OAuth authentication and session management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from arr_mcp.config import Settings
from arr_mcp.dashboard.auth import (
    AuthUser,
    PlexPin,
    SessionManager,
    build_auth_user,
    build_plex_auth_url,
    create_plex_pin,
    get_plex_user_info,
    poll_plex_pin,
)
from arr_mcp.server import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
        dashboard_public=False,
        session_secret="test-secret-32-bytes-long-abcdef",
        admin_plex_users=["adminuser"],
    )


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
        dashboard_public=True,
        session_secret="test-secret-32-bytes-long-abcdef",
        admin_plex_users=["adminuser"],
    )


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
    user = AuthUser(plex_id="123", plex_username="alice", is_admin=True, avatar_url="https://img")
    token = sm.sign(user)
    result = sm.verify(token)
    assert result is not None
    assert result.plex_id == "123"
    assert result.plex_username == "alice"
    assert result.is_admin is True
    assert result.avatar_url == "https://img"


def test_session_rejects_tampered_token():
    sm = SessionManager("test-secret")
    user = AuthUser(plex_id="123", plex_username="alice", is_admin=False)
    token = sm.sign(user)
    tampered = token[:-4] + "xxxx"
    assert sm.verify(tampered) is None


def test_session_rejects_wrong_secret():
    sm1 = SessionManager("secret-one")
    sm2 = SessionManager("secret-two")
    user = AuthUser(plex_id="1", plex_username="bob", is_admin=False)
    token = sm1.sign(user)
    assert sm2.verify(token) is None


def test_session_none_avatar_preserved():
    sm = SessionManager("test-secret")
    user = AuthUser(plex_id="99", plex_username="carol", is_admin=False, avatar_url=None)
    token = sm.sign(user)
    result = sm.verify(token)
    assert result is not None
    assert result.avatar_url is None


# ---------------------------------------------------------------------------
# build_auth_user
# ---------------------------------------------------------------------------


def test_build_auth_user_admin():
    info = {"id": 42, "username": "adminuser", "thumb": "https://avatar"}
    user = build_auth_user(info, admin_users=["adminuser", "other"])
    assert user.plex_id == "42"
    assert user.plex_username == "adminuser"
    assert user.is_admin is True
    assert user.avatar_url == "https://avatar"


def test_build_auth_user_non_admin():
    info = {"id": 7, "username": "regular", "thumb": None}
    user = build_auth_user(info, admin_users=["adminuser"])
    assert user.is_admin is False


def test_build_auth_user_case_insensitive_admin():
    info = {"id": 5, "username": "AdminUser"}
    user = build_auth_user(info, admin_users=["adminuser"])
    assert user.is_admin is True


def test_build_auth_user_empty_admin_list():
    info = {"id": 1, "username": "anyone"}
    user = build_auth_user(info, admin_users=[])
    assert user.is_admin is False


# ---------------------------------------------------------------------------
# build_plex_auth_url
# ---------------------------------------------------------------------------


def test_build_plex_auth_url_contains_code():
    pin = PlexPin(id="12345", code="abcdef12")
    url = build_plex_auth_url(pin, "http://localhost:8081/auth/plex/callback?pin_id=12345")
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
# Auth routes — sign-in page
# ---------------------------------------------------------------------------


async def test_auth_signin_returns_200(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/signin")
    assert r.status_code == 200
    assert "Sign in with Plex" in r.text


async def test_auth_signin_shows_error_param(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/auth/signin?error=Something+went+wrong.")
    assert "Something went wrong." in r.text


# ---------------------------------------------------------------------------
# Auth routes — /auth/plex/start
# ---------------------------------------------------------------------------


async def test_auth_plex_start_redirects_to_plex(private_settings: Settings) -> None:
    app = _make_app(private_settings)
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


async def test_auth_plex_start_handles_pin_failure(private_settings: Settings) -> None:
    app = _make_app(private_settings)
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
    private_settings: Settings,
) -> None:
    app = _make_app(private_settings)
    with (
        patch(
            "arr_mcp.dashboard.routes.poll_plex_pin",
            new=AsyncMock(return_value="auth-token-xyz"),
        ),
        patch(
            "arr_mcp.dashboard.routes.get_plex_user_info",
            new=AsyncMock(return_value={"id": 42, "username": "alice", "thumb": None}),
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


async def test_auth_plex_callback_missing_pin_id(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        r = await client.get("/auth/plex/callback")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]


async def test_auth_plex_callback_pin_not_claimed(private_settings: Settings) -> None:
    app = _make_app(private_settings)
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


async def test_auth_plex_callback_user_info_failure(private_settings: Settings) -> None:
    app = _make_app(private_settings)
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
# Auth routes — /auth/logout
# ---------------------------------------------------------------------------


async def test_auth_logout_clears_cookie(private_settings: Settings) -> None:
    app = _make_app(private_settings)
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


async def test_dashboard_accepts_valid_session_cookie(private_settings: Settings) -> None:
    from arr_mcp.dashboard.auth import AuthUser, SessionManager

    sm = SessionManager(private_settings.session_secret)
    token = sm.sign(AuthUser(plex_id="1", plex_username="alice", is_admin=False))

    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"arr_mcp_session": token},
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 200


async def test_dashboard_rejects_invalid_session_cookie(private_settings: Settings) -> None:
    app = _make_app(private_settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"arr_mcp_session": "not-a-valid-token"},
        follow_redirects=False,
    ) as client:
        r = await client.get("/")
    assert r.status_code == 302
    assert "/auth/signin" in r.headers["location"]

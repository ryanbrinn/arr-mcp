"""Plex PIN OAuth flow and session cookie management for the dashboard."""

from __future__ import annotations

import logging
import secrets as _secrets_mod
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request

    from arr_mcp.config import Settings

log = logging.getLogger(__name__)

_PLEX_TV_PINS_URL = "https://plex.tv/api/v2/pins"
_PLEX_TV_USER_URL = "https://plex.tv/api/v2/user"
_PLEX_AUTH_URL = "https://app.plex.tv/auth"
_CLIENT_IDENTIFIER = "arr-mcp"
_SESSION_COOKIE_NAME = "arr_mcp_session"
_SESSION_MAX_AGE = 86400 * 7  # 7 days


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AuthUser:
    """An authenticated dashboard user."""

    plex_id: str
    plex_username: str
    is_admin: bool
    avatar_url: str | None = None


@dataclass
class PlexPin:
    """A short-lived authorization PIN from plex.tv."""

    id: str
    code: str


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_process_secret: str | None = None


def _get_process_secret() -> str:
    """Return a stable per-process fallback secret (does not survive restarts)."""
    global _process_secret
    if _process_secret is None:
        _process_secret = _secrets_mod.token_hex(32)
        log.warning(
            "ARR_MCP_SESSION_SECRET is not set — sessions will not survive restarts. "
            "Set ARR_MCP_SESSION_SECRET for persistent sessions."
        )
    return _process_secret


class SessionManager:
    """Signs and verifies dashboard session cookies using itsdangerous."""

    def __init__(self, secret: str) -> None:
        effective = secret if secret else _get_process_secret()
        self._s = URLSafeTimedSerializer(effective, salt="arr-mcp-session")

    def sign(self, user: AuthUser) -> str:
        """Return a signed session token for user."""
        return self._s.dumps(  # type: ignore[no-any-return]
            {
                "pid": user.plex_id,
                "usr": user.plex_username,
                "adm": user.is_admin,
                "ava": user.avatar_url,
            }
        )

    def verify(self, token: str) -> AuthUser | None:
        """Return the AuthUser encoded in token, or None if invalid or expired."""
        try:
            payload: dict[str, Any] = self._s.loads(token, max_age=_SESSION_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return None
        return AuthUser(
            plex_id=str(payload.get("pid", "")),
            plex_username=str(payload.get("usr", "")),
            is_admin=bool(payload.get("adm")),
            avatar_url=payload.get("ava"),
        )


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def get_session_user(request: Request, settings: Settings) -> AuthUser | None:
    """Extract and verify the session cookie; return AuthUser or None."""
    token = request.cookies.get(_SESSION_COOKIE_NAME)
    if not token:
        return None
    return SessionManager(settings.session_secret).verify(token)


def set_session_cookie(response: Response, user: AuthUser, settings: Settings) -> None:
    """Attach a signed session cookie to response."""
    token = SessionManager(settings.session_secret).sign(user)
    response.set_cookie(
        _SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from response."""
    response.delete_cookie(_SESSION_COOKIE_NAME)


# ---------------------------------------------------------------------------
# Plex PIN OAuth helpers
# ---------------------------------------------------------------------------


async def create_plex_pin(*, http: httpx.AsyncClient | None = None) -> PlexPin | None:
    """Request a new PIN from plex.tv. Returns None on failure."""
    headers = {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": _CLIENT_IDENTIFIER,
        "X-Plex-Product": "arr-mcp",
    }

    async def _call(client: httpx.AsyncClient) -> PlexPin | None:
        try:
            resp = await client.post(
                _PLEX_TV_PINS_URL,
                headers=headers,
                params={"strong": "true"},
                timeout=10.0,
            )
            if not resp.is_success:
                log.warning("Plex PIN creation failed: HTTP %s", resp.status_code)
                return None
            data: dict[str, Any] = resp.json()
            return PlexPin(id=str(data["id"]), code=str(data["code"]))
        except Exception as exc:
            log.warning("Plex PIN creation error: %s", exc)
            return None

    if http is not None:
        return await _call(http)
    async with httpx.AsyncClient() as client:
        return await _call(client)


def build_plex_auth_url(pin: PlexPin, callback_url: str) -> str:
    """Build the plex.tv browser auth URL including a fragment with OAuth params."""
    params = urllib.parse.urlencode(
        {
            "clientID": _CLIENT_IDENTIFIER,
            "code": pin.code,
            "forwardUrl": callback_url,
            "context[device][product]": "arr-mcp",
        }
    )
    return f"{_PLEX_AUTH_URL}#{params}"


async def poll_plex_pin(pin_id: str, *, http: httpx.AsyncClient | None = None) -> str | None:
    """Return the auth token once the PIN is claimed, or None if not yet available."""
    url = f"{_PLEX_TV_PINS_URL}/{pin_id}"
    headers = {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": _CLIENT_IDENTIFIER,
    }

    async def _call(client: httpx.AsyncClient) -> str | None:
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if not resp.is_success:
                return None
            data: dict[str, Any] = resp.json()
            return data.get("authToken") or None
        except Exception as exc:
            log.warning("Plex PIN poll error: %s", exc)
            return None

    if http is not None:
        return await _call(http)
    async with httpx.AsyncClient() as client:
        return await _call(client)


async def get_plex_user_info(
    auth_token: str, *, http: httpx.AsyncClient | None = None
) -> dict[str, Any] | None:
    """Fetch user info from plex.tv using the given auth token."""
    headers = {
        "Accept": "application/json",
        "X-Plex-Token": auth_token,
        "X-Plex-Client-Identifier": _CLIENT_IDENTIFIER,
    }

    async def _call(client: httpx.AsyncClient) -> dict[str, Any] | None:
        try:
            resp = await client.get(_PLEX_TV_USER_URL, headers=headers, timeout=10.0)
            if not resp.is_success:
                log.warning("Plex user info failed: HTTP %s", resp.status_code)
                return None
            return resp.json()  # type: ignore[no-any-return]
        except Exception as exc:
            log.warning("Plex user info error: %s", exc)
            return None

    if http is not None:
        return await _call(http)
    async with httpx.AsyncClient() as client:
        return await _call(client)


def build_auth_user(user_info: dict[str, Any], admin_users: list[str]) -> AuthUser:
    """Build an AuthUser from a plex.tv /api/v2/user response payload."""
    username = str(user_info.get("username", ""))
    admins_lower = {u.strip().lower() for u in admin_users if u.strip()}
    return AuthUser(
        plex_id=str(user_info.get("id", "")),
        plex_username=username,
        is_admin=username.lower() in admins_lower,
        avatar_url=user_info.get("thumb"),
    )

"""Plex PIN OAuth flow, local accounts, and session management for the dashboard."""

from __future__ import annotations

import ipaddress
import logging
import secrets as _secrets_mod
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import Response

from arr_mcp.services.base import ServiceNotConfiguredError
from arr_mcp.services.users import AppUser, UserStore

if TYPE_CHECKING:
    from starlette.requests import Request

    from arr_mcp.config import Settings
    from arr_mcp.services.plex import PlexClient

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
    """An authenticated dashboard user, backed by an AppUser identity."""

    app_user_id: str
    display_name: str
    is_admin: bool
    avatar_url: str | None = None
    session_provider: str = "local"


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
        return self._s.dumps(
            {
                "uid": user.app_user_id,
                "name": user.display_name,
                "adm": user.is_admin,
                "ava": user.avatar_url,
                "prv": user.session_provider,
            }
        )

    def verify(self, token: str) -> AuthUser | None:
        """Return the AuthUser encoded in token, or None if invalid or expired."""
        try:
            payload: dict[str, Any] = self._s.loads(token, max_age=_SESSION_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return None
        uid = payload.get("uid")
        if not uid:
            return None
        return AuthUser(
            app_user_id=str(uid),
            display_name=str(payload.get("name", "")),
            is_admin=bool(payload.get("adm")),
            avatar_url=payload.get("ava"),
            session_provider=str(payload.get("prv", "local")),
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


def is_local_request(request: Request) -> bool:
    """Return True if Plex OAuth likely can't redirect back to this request.

    Plex's auth app only honours ``forwardUrl`` for https or publicly
    recognised domains. On http, localhost, or a private-network address it
    redirects to ``watch.plex.tv/me`` instead of completing sign-in.
    """
    url = request.url
    if url.scheme != "https":
        return True
    hostname = url.hostname or ""
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_private
    except ValueError:
        return False


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


async def poll_plex_pin(
    pin_id: str, *, http: httpx.AsyncClient | None = None
) -> str | None:
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


# ---------------------------------------------------------------------------
# AppUser-aware auth flows
# ---------------------------------------------------------------------------


async def _detect_plex_home_admin(
    plex_id: str, settings: Settings, *, http: httpx.AsyncClient | None = None
) -> bool:
    """Return True if *plex_id* is an admin per the server's home-users list.

    Returns False if no Plex credential is configured or the lookup fails —
    callers should treat this as "unknown", not "explicitly not admin".
    """
    try:
        from arr_mcp.services.registry import ServiceRegistry

        registry = ServiceRegistry(settings.services_dir, http=http)
        plex = cast("PlexClient", registry.get_client("plex"))
        result = await plex.get_home_users()
        if not result.ok:
            return False
        for user in result.data or []:  # type: ignore[union-attr]
            if user.id == plex_id:
                return user.is_admin
    except ServiceNotConfiguredError:
        return False
    except Exception as exc:
        log.warning("Could not determine Plex home-user admin status: %s", exc)
    return False


async def build_auth_user_plex(
    user_info: dict[str, Any],
    settings: Settings,
    *,
    http: httpx.AsyncClient | None = None,
) -> AuthUser:
    """Resolve a Plex login to an AppUser, auto-provisioning/linking as needed.

    Admin status is granted via the Plex home-user ``admin`` flag, the
    ``admin_users`` config list, or — for the very first AppUser ever
    created — unconditionally. Admin status is sticky: once granted it is
    never auto-revoked on subsequent logins.
    """
    plex_id = str(user_info.get("id", ""))
    username = str(user_info.get("username", ""))
    avatar = user_info.get("thumb")

    admins_lower = {u.strip().lower() for u in settings.admin_users if u.strip()}
    config_admin = username.lower() in admins_lower

    user_store = UserStore(settings.services_dir)
    is_first_user = not user_store.has_any()

    existing = user_store.find_by_linked_identity("plex", plex_id)
    if existing is not None:
        home_admin = await _detect_plex_home_admin(plex_id, settings, http=http)
        is_admin = existing.is_admin or home_admin or config_admin
        user_store.update_profile(
            existing.app_user_id,
            display_name=username,
            avatar_url=avatar,
            is_admin=is_admin,
        )
        return AuthUser(
            app_user_id=existing.app_user_id,
            display_name=username,
            is_admin=is_admin,
            avatar_url=avatar,
            session_provider="plex",
        )

    home_admin = await _detect_plex_home_admin(plex_id, settings, http=http)
    is_admin = is_first_user or home_admin or config_admin
    created = user_store.create_linked(
        "plex",
        plex_id,
        username,
        is_admin=is_admin,
        avatar_url=avatar,
    )
    return AuthUser(
        app_user_id=created.app_user_id,
        display_name=username,
        is_admin=created.is_admin,
        avatar_url=avatar,
        session_provider="plex",
    )


def needs_first_run_setup(settings: Settings) -> bool:
    """Return True when no AppUser exists yet — first-run setup must be shown."""
    return not UserStore(settings.services_dir).has_any()


def verify_local_login(
    username: str, password: str, settings: Settings
) -> AuthUser | None:
    """Verify local username/password credentials and return an AuthUser."""
    user_store = UserStore(settings.services_dir)
    user = user_store.find_by_username(username)
    if user is None:
        return None
    if not user_store.verify_password(user.app_user_id, password):
        return None
    return AuthUser(
        app_user_id=user.app_user_id,
        display_name=user.display_name,
        is_admin=user.is_admin,
        avatar_url=user.avatar_url,
        session_provider="local",
    )


def create_first_run_local_admin(
    display_name: str, password: str, settings: Settings
) -> AuthUser | None:
    """Create the first AppUser as a local admin account.

    Returns None if an AppUser already exists (race) or the display name is
    taken.
    """
    user_store = UserStore(settings.services_dir)
    if user_store.has_any():
        return None
    user = user_store.create_local(display_name, password, is_admin=True)
    if user is None:
        return None
    return AuthUser(
        app_user_id=user.app_user_id,
        display_name=user.display_name,
        is_admin=user.is_admin,
        avatar_url=user.avatar_url,
        session_provider="local",
    )


def has_linked_plex(app_user_id: str, settings: Settings) -> bool:
    """Return True if the given AppUser has a linked Plex identity."""
    user = UserStore(settings.services_dir).get(app_user_id)
    if user is None:
        return False
    return "plex" in user.linked_identities


def link_plex_identity(
    app_user_id: str, plex_id: str, settings: Settings
) -> AppUser | None:
    """Link a Plex identity to an existing AppUser.

    Returns None if the Plex identity is already linked to a *different*
    AppUser.
    """
    user_store = UserStore(settings.services_dir)
    existing = user_store.find_by_linked_identity("plex", plex_id)
    if existing is not None and existing.app_user_id != app_user_id:
        return None
    user_store.link_identity(app_user_id, "plex", plex_id)
    return user_store.get(app_user_id)

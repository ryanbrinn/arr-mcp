"""Dashboard route handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from arr_mcp.config import Settings
from arr_mcp.dashboard.auth import (
    build_auth_user,
    build_plex_auth_url,
    clear_session_cookie,
    create_plex_pin,
    get_plex_user_info,
    get_session_user,
    poll_plex_pin,
    set_session_cookie,
)
from arr_mcp.dashboard.data import get_status
from arr_mcp.dashboard.diagnose import diagnose
from arr_mcp.runtime.client import ContainerClient

if TYPE_CHECKING:
    from arr_mcp.ai.provider import AIProvider

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Known service name fragments → short label shown in the icon badge.
# Matched case-insensitively against the container name.
_SERVICE_LABELS: dict[str, str] = {
    "sonarr": "SN",
    "radarr": "RD",
    "prowlarr": "PR",
    "bazarr": "BZ",
    "lidarr": "LI",
    "readarr": "RE",
    "overseerr": "OV",
    "jellyseerr": "JS",
    "plex": "PX",
    "jellyfin": "JF",
    "emby": "EM",
    "sabnzbd": "SAB",
    "nzbget": "NZB",
    "qbittorrent": "QB",
    "deluge": "DL",
    "transmission": "TR",
    "nginx": "NX",
    "traefik": "TK",
    "certbot": "CB",
    "fail2ban": "F2B",
    "portainer": "PT",
    "watchtower": "WT",
    "arr-mcp": "MCP",
    "arr-agent": "AG",
}


def _service_icon(name: str) -> str:
    """Return a short label for a known service, or the first two chars of the name."""
    lower = name.lower()
    for fragment, label in _SERVICE_LABELS.items():
        if fragment in lower:
            return label
    return name[:2].upper() if name else "?"


def _fmt_uptime(seconds: int) -> str:
    """Format uptime seconds into a human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h, m = divmod(seconds, 3600)
        return f"{h}h {m // 60}m"
    d, rem = divmod(seconds, 86400)
    return f"{d}d {rem // 3600}h"


def _get_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["uptime"] = _fmt_uptime
    env.filters["service_icon"] = _service_icon
    return env


def _check_auth(request: Request, settings: Settings) -> bool:
    """Return True if the request is authorised to view the dashboard."""
    if settings.dashboard_public:
        return True
    if get_session_user(request, settings) is not None:
        return True
    key = request.query_params.get("key", "")
    return bool(key) and key == settings.api_key


def make_dashboard_routes(
    client: ContainerClient,
    settings: Settings,
    ai_provider: AIProvider | None = None,
) -> dict[str, Any]:
    """Return the dashboard route handlers as a dict."""
    jinja = _get_jinja_env()

    async def handle_dashboard(request: Request) -> Response:
        """Serve the HTML dashboard."""
        if not _check_auth(request, settings):
            return RedirectResponse(url="/auth/signin", status_code=302)
        try:
            status = await get_status(client, settings)
        except Exception as exc:
            log.exception("Error building dashboard status")
            return HTMLResponse(f"<h1>Error</h1><pre>{exc}</pre>", status_code=500)

        template = jinja.get_template("index.html")
        html = template.render(status=status, settings=settings)
        return HTMLResponse(html)

    async def handle_api_status(request: Request) -> Response:
        """Return JSON status data."""
        if not _check_auth(request, settings):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            status = await get_status(client, settings)
        except Exception as exc:
            log.exception("Error building API status")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(status)

    async def handle_api_diagnose(request: Request) -> Response:
        """Run contextual AI diagnosis on a specific issue type.

        POST /api/diagnose
        Body: {"issue_type": str, "context": dict}

        Returns: {"narrative": str, "remedies": [{label, tool, args}]}

        When no AI provider is configured, returns rule-based remedies only.
        """
        if not _check_auth(request, settings):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        issue_type = body.get("issue_type", "")
        context = body.get("context", {})

        if not issue_type:
            return JSONResponse({"error": "issue_type is required"}, status_code=400)

        if not isinstance(context, dict):
            return JSONResponse({"error": "context must be an object"}, status_code=400)

        if ai_provider is None:
            from arr_mcp.ai.null import NullProvider

            provider = NullProvider()
        else:
            provider = ai_provider

        try:
            result = await diagnose(provider, issue_type, context)
        except Exception as exc:
            log.exception("Diagnose handler error for issue_type=%s", issue_type)
            return JSONResponse({"error": str(exc)}, status_code=500)

        return JSONResponse(result)

    async def handle_auth_signin(request: Request) -> Response:
        """Render the Plex sign-in page."""
        error = request.query_params.get("error", "")
        template = jinja.get_template("signin.html")
        html = template.render(error=error)
        return HTMLResponse(html)

    async def handle_auth_plex_start(request: Request) -> Response:
        """Create a Plex PIN and redirect the browser to plex.tv auth."""
        base = str(request.base_url).rstrip("/")
        pin = await create_plex_pin()
        if pin is None:
            return RedirectResponse(
                url="/auth/signin?error=Could+not+reach+plex.tv.+Try+again+later.",
                status_code=302,
            )
        callback_url = f"{base}/auth/plex/callback?pin_id={pin.id}"
        return RedirectResponse(url=build_plex_auth_url(pin, callback_url), status_code=302)

    async def handle_auth_plex_callback(request: Request) -> Response:
        """Exchange a claimed Plex PIN for an auth token, then issue a session cookie."""
        pin_id = request.query_params.get("pin_id", "")
        if not pin_id:
            return RedirectResponse(url="/auth/signin?error=Missing+PIN+ID.", status_code=302)

        auth_token = await poll_plex_pin(pin_id)
        if not auth_token:
            return RedirectResponse(
                url="/auth/signin?error=Plex+authorisation+was+not+completed.+Please+try+again.",
                status_code=302,
            )

        user_info = await get_plex_user_info(auth_token)
        if not user_info:
            return RedirectResponse(
                url="/auth/signin?error=Could+not+fetch+user+info+from+plex.tv.",
                status_code=302,
            )

        user = build_auth_user(user_info, settings.admin_plex_users)
        response = RedirectResponse(url="/", status_code=302)
        set_session_cookie(response, user, settings)
        return response

    async def handle_auth_logout(request: Request) -> Response:
        """Clear the session cookie and redirect to sign-in."""
        response = RedirectResponse(url="/auth/signin", status_code=302)
        clear_session_cookie(response)
        return response

    return {
        "dashboard": handle_dashboard,
        "api_status": handle_api_status,
        "api_diagnose": handle_api_diagnose,
        "auth_signin": handle_auth_signin,
        "auth_plex_start": handle_auth_plex_start,
        "auth_plex_callback": handle_auth_plex_callback,
        "auth_logout": handle_auth_logout,
    }

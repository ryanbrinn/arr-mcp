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
from arr_mcp.dashboard.data import get_insights, get_status
from arr_mcp.dashboard.diagnose import diagnose
from arr_mcp.runtime.client import ContainerClient

if TYPE_CHECKING:
    from arr_mcp.ai.provider import AIProvider

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    import json

    from markupsafe import Markup

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["tojson"] = lambda v: Markup(json.dumps(v))
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

        try:
            insights: list[dict[str, Any]] = await get_insights(status, ai_provider)
        except Exception:
            log.exception("Error generating AI insights")
            insights = []

        template = jinja.get_template("index.html")
        html = template.render(status=status, insights=insights, settings=settings)
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

        provider: AIProvider
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

    async def handle_api_series_episodes(request: Request) -> Response:
        """Return episodes for a series, optionally filtered by season.

        GET /api/series/{id}/episodes?season=N
        """
        if not _check_auth(request, settings):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        from arr_mcp.services.base import ServiceNotConfiguredError
        from arr_mcp.services.registry import ServiceRegistry

        series_id = request.path_params["id"]
        season = request.query_params.get("season")

        registry = ServiceRegistry(settings.services_dir)
        try:
            sonarr = registry.get_client("sonarr")
        except ServiceNotConfiguredError:
            return JSONResponse({"error": "Sonarr is not configured"}, status_code=404)

        try:
            result = await sonarr.get_episodes(series_id)  # type: ignore[attr-defined]
        except Exception as exc:
            log.exception("Error fetching episodes for series_id=%s", series_id)
            return JSONResponse({"error": str(exc)}, status_code=500)

        if not result.ok or not isinstance(result.data, list):
            error = result.error or "Unknown error"
            return JSONResponse({"error": error}, status_code=502)

        episodes = result.data
        if season is not None:
            try:
                season_num = int(season)
                episodes = [e for e in episodes if e.season_number == season_num]
            except ValueError:
                pass

        episodes.sort(key=lambda e: e.episode_number)

        return JSONResponse(
            {
                "episodes": [
                    {
                        "episode_number": e.episode_number,
                        "season_number": e.season_number,
                        "title": e.title,
                        "has_file": e.has_file,
                    }
                    for e in episodes
                ]
            }
        )

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
        return RedirectResponse(
            url=build_plex_auth_url(pin, callback_url), status_code=302
        )

    async def handle_auth_plex_callback(request: Request) -> Response:
        """Exchange a Plex PIN for an auth token, then issue a session cookie."""
        pin_id = request.query_params.get("pin_id", "")
        if not pin_id:
            return RedirectResponse(
                url="/auth/signin?error=Missing+PIN+ID.", status_code=302
            )

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
        "api_series_episodes": handle_api_series_episodes,
        "auth_signin": handle_auth_signin,
        "auth_plex_start": handle_auth_plex_start,
        "auth_plex_callback": handle_auth_plex_callback,
        "auth_logout": handle_auth_logout,
    }

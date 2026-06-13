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
    build_auth_user_plex,
    build_plex_auth_url,
    clear_session_cookie,
    create_first_run_local_admin,
    create_plex_pin,
    get_plex_user_info,
    get_session_user,
    has_linked_plex,
    is_local_request,
    link_plex_identity,
    needs_first_run_setup,
    poll_plex_pin,
    set_session_cookie,
    verify_local_login,
)
from arr_mcp.dashboard.data import get_insights, get_status
from arr_mcp.dashboard.diagnose import diagnose
from arr_mcp.runtime.client import ContainerClient

if TYPE_CHECKING:
    from arr_mcp.ai.provider import AIProvider

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    from jinja2.utils import htmlsafe_json_dumps

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["tojson"] = htmlsafe_json_dumps
    return env


def _check_auth(request: Request, settings: Settings) -> bool:
    """Return True if the request is authorised to view the dashboard."""
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
        if needs_first_run_setup(settings):
            return RedirectResponse(url="/auth/setup", status_code=302)
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

        user = get_session_user(request, settings)
        linked_plex = (
            has_linked_plex(user.app_user_id, settings) if user is not None else False
        )

        template = jinja.get_template("index.html")
        html = template.render(
            status=status,
            insights=insights,
            settings=settings,
            user=user,
            linked_plex=linked_plex,
        )
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

    async def handle_api_interest(request: Request) -> Response:
        """Set the signed-in user's interest state for a piece of content.

        POST /api/interest
        Body: {"content_id": str, "content_type": "movie"|"episode", "state": str}
        or {"content_ids": [str, ...], ...} to set multiple at once (e.g. a
        whole season).

        Returns: {"ok": true}
        """
        from arr_mcp.services.interests import InterestState, InterestStore

        user = get_session_user(request, settings)
        if user is None:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        content_ids = body.get("content_ids")
        if content_ids is None:
            content_id = body.get("content_id")
            content_ids = [content_id] if content_id else []
        content_type = body.get("content_type", "unknown")
        state_value = body.get("state", "")

        if not content_ids or not isinstance(content_ids, list):
            return JSONResponse({"error": "content_id(s) is required"}, status_code=400)
        if content_type not in ("movie", "episode"):
            return JSONResponse(
                {"error": "content_type must be 'movie' or 'episode'"}, status_code=400
            )
        try:
            state = InterestState(state_value)
        except ValueError:
            return JSONResponse(
                {"error": f"Invalid state: {state_value!r}"}, status_code=400
            )

        store = InterestStore(settings.services_dir)
        for content_id in content_ids:
            store.set(
                str(content_id),
                user.app_user_id,
                state,
                username=user.display_name,
                content_type=content_type,
            )

        return JSONResponse({"ok": True})

    async def handle_auth_signin(request: Request) -> Response:
        """Render the sign-in page."""
        if needs_first_run_setup(settings):
            return RedirectResponse(url="/auth/setup", status_code=302)
        error = request.query_params.get("error", "")
        template = jinja.get_template("signin.html")
        html = template.render(error=error, is_local=is_local_request(request))
        return HTMLResponse(html)

    async def handle_auth_setup(request: Request) -> Response:
        """First-run setup: create the initial local admin account."""
        if not needs_first_run_setup(settings):
            return RedirectResponse(url="/auth/signin", status_code=302)

        if request.method == "GET":
            error = request.query_params.get("error", "")
            template = jinja.get_template("setup.html")
            html = template.render(error=error)
            return HTMLResponse(html)

        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        confirm = str(form.get("confirm_password", ""))

        if not username or not password:
            return RedirectResponse(
                url="/auth/setup?error=Username+and+password+are+required.",
                status_code=302,
            )
        if len(password) < 8:
            return RedirectResponse(
                url="/auth/setup?error=Password+must+be+at+least+8+characters.",
                status_code=302,
            )
        if password != confirm:
            return RedirectResponse(
                url="/auth/setup?error=Passwords+do+not+match.", status_code=302
            )

        user = create_first_run_local_admin(username, password, settings)
        if user is None:
            return RedirectResponse(
                url="/auth/setup?error=Setup+has+already+been+completed.",
                status_code=302,
            )

        response = RedirectResponse(url="/", status_code=302)
        set_session_cookie(response, user, settings)
        return response

    async def handle_auth_local_login(request: Request) -> Response:
        """Verify local username/password credentials and issue a session."""
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))

        user = verify_local_login(username, password, settings)
        if user is None:
            return RedirectResponse(
                url="/auth/signin?error=Invalid+username+or+password.",
                status_code=302,
            )

        response = RedirectResponse(url="/", status_code=302)
        set_session_cookie(response, user, settings)
        return response

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

        user = await build_auth_user_plex(user_info, settings)
        response = RedirectResponse(url="/", status_code=302)
        set_session_cookie(response, user, settings)
        return response

    async def handle_auth_logout(request: Request) -> Response:
        """Clear the session cookie and redirect to sign-in."""
        response = RedirectResponse(url="/auth/signin", status_code=302)
        clear_session_cookie(response)
        return response

    async def handle_auth_link_plex(request: Request) -> Response:
        """Render a landing page explaining Plex linking before starting it."""
        user = get_session_user(request, settings)
        if user is None:
            return RedirectResponse(url="/auth/signin", status_code=302)
        template = jinja.get_template("link_plex.html")
        html = template.render(is_local=is_local_request(request))
        return HTMLResponse(html)

    async def handle_auth_link_plex_start(request: Request) -> Response:
        """Create a Plex PIN to link a Plex account to the signed-in user."""
        user = get_session_user(request, settings)
        if user is None:
            return RedirectResponse(url="/auth/signin", status_code=302)

        base = str(request.base_url).rstrip("/")
        pin = await create_plex_pin()
        if pin is None:
            return RedirectResponse(
                url="/?error=Could+not+reach+plex.tv.+Try+again+later.",
                status_code=302,
            )
        callback_url = f"{base}/auth/link/plex/callback?pin_id={pin.id}"
        return RedirectResponse(
            url=build_plex_auth_url(pin, callback_url), status_code=302
        )

    async def handle_auth_link_plex_callback(request: Request) -> Response:
        """Exchange a Plex PIN and link the resulting account to the session user."""
        user = get_session_user(request, settings)
        if user is None:
            return RedirectResponse(url="/auth/signin", status_code=302)

        pin_id = request.query_params.get("pin_id", "")
        if not pin_id:
            return RedirectResponse(url="/?error=Missing+PIN+ID.", status_code=302)

        auth_token = await poll_plex_pin(pin_id)
        if not auth_token:
            return RedirectResponse(
                url="/?error=Plex+authorisation+was+not+completed.+Please+try+again.",
                status_code=302,
            )

        user_info = await get_plex_user_info(auth_token)
        if not user_info:
            return RedirectResponse(
                url="/?error=Could+not+fetch+user+info+from+plex.tv.", status_code=302
            )

        plex_id = str(user_info.get("id", ""))
        linked = link_plex_identity(user.app_user_id, plex_id, settings)
        if linked is None:
            return RedirectResponse(
                url="/?error=This+Plex+account+is+already+linked+to+another+user.",
                status_code=302,
            )

        return RedirectResponse(url="/", status_code=302)

    return {
        "dashboard": handle_dashboard,
        "api_status": handle_api_status,
        "api_diagnose": handle_api_diagnose,
        "api_interest": handle_api_interest,
        "auth_signin": handle_auth_signin,
        "auth_setup": handle_auth_setup,
        "auth_local_login": handle_auth_local_login,
        "auth_plex_start": handle_auth_plex_start,
        "auth_plex_callback": handle_auth_plex_callback,
        "auth_link_plex": handle_auth_link_plex,
        "auth_link_plex_start": handle_auth_link_plex_start,
        "auth_link_plex_callback": handle_auth_link_plex_callback,
        "auth_logout": handle_auth_logout,
    }

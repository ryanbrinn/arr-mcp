"""arr-mcp: MCP server for home media stack management."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp

from arr_mcp.ai.provider import AIProvider, get_provider
from arr_mcp.config import Settings
from arr_mcp.dashboard.routes import make_dashboard_routes
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.tasks.alerts import AlertWatcher
from arr_mcp.tasks.media_interest import MediaInterestChecker
from arr_mcp.tasks.versions import VersionChecker
from arr_mcp.tools.alerts import register_alert_tools
from arr_mcp.tools.containers import register_container_tools
from arr_mcp.tools.conversion import register_conversion_tools
from arr_mcp.tools.credentials import register_credential_tools
from arr_mcp.tools.diagnostics import register_diagnostic_tools
from arr_mcp.tools.filesystem import register_filesystem_tools
from arr_mcp.tools.interests import register_interest_tools
from arr_mcp.tools.logs import register_log_tools
from arr_mcp.tools.media import register_media_tools
from arr_mcp.tools.reachability import register_reachability_tools
from arr_mcp.tools.stacks import register_stack_tools
from arr_mcp.tools.versions import register_version_tools

load_dotenv()

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "dashboard" / "static"


def build_mcp_server(
    settings: Settings, client: ContainerClient, ai_provider: AIProvider
) -> FastMCP:
    """Build and configure the FastMCP server with all tool registrations."""
    # Disable DNS rebinding protection — we use API key auth instead and the
    # server is accessed from external hosts (not just localhost).
    server = FastMCP(
        "arr-mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    register_container_tools(server, client)
    if settings.is_compose:
        register_stack_tools(server, client, settings)
    register_filesystem_tools(server, settings)
    register_log_tools(server, settings)
    register_conversion_tools(server, settings)
    register_diagnostic_tools(server, settings, client)
    register_alert_tools(server, settings)
    register_credential_tools(server, settings)
    register_interest_tools(server, settings)
    register_media_tools(server, settings)
    register_reachability_tools(server, settings)
    register_version_tools(server, settings)
    return server


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Health, dashboard, and static assets bypass Bearer auth —
        # the dashboard does its own key-in-query-param check.
        path = request.url.path
        is_dashboard = (
            path in ("/health", "/", "/api/status", "/api/diagnose", "/api/interest")
            or path.startswith("/static/")
            or path.startswith("/auth/")
        )
        if is_dashboard:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[len("Bearer ") :] != self.api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def create_app(settings: Settings) -> Starlette:
    """Build the Starlette ASGI app with auth middleware and MCP route."""
    client = ContainerClient(settings)
    ai_provider = get_provider(settings)
    mcp_server = build_mcp_server(settings, client, ai_provider)

    # Initialise the session manager and extract the /mcp route handler.
    # We then run session_manager.run() in our own lifespan so the task group
    # is always initialised before requests arrive, regardless of whether the
    # host (uvicorn or httpx test transport) calls sub-app lifespans.
    fastmcp_app = mcp_server.streamable_http_app()
    mcp_route = fastmcp_app.routes[0]  # Route("/mcp", endpoint=StreamableHTTPASGIApp)

    alert_watcher = AlertWatcher(settings)
    version_checker = VersionChecker(settings)
    media_interest_checker = MediaInterestChecker(settings)
    dashboard = make_dashboard_routes(client, settings, ai_provider)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        log.info(
            "arr-mcp starting — runtime=%s port=%d",
            settings.container_runtime,
            settings.port,
        )
        async with mcp_server.session_manager.run():
            async with anyio.create_task_group() as tg:
                tg.start_soon(alert_watcher.run)
                tg.start_soon(version_checker.run)
                tg.start_soon(media_interest_checker.run)
                yield
                tg.cancel_scope.cancel()
        log.info("arr-mcp stopped")

    routes = [
        Route("/health", endpoint=health_check),
        Route("/", endpoint=dashboard["dashboard"]),
        Route("/api/status", endpoint=dashboard["api_status"]),
        Route("/api/diagnose", endpoint=dashboard["api_diagnose"], methods=["POST"]),
        Route("/api/interest", endpoint=dashboard["api_interest"], methods=["POST"]),
        Route("/auth/signin", endpoint=dashboard["auth_signin"]),
        Route("/auth/setup", endpoint=dashboard["auth_setup"], methods=["GET", "POST"]),
        Route(
            "/auth/local/login",
            endpoint=dashboard["auth_local_login"],
            methods=["POST"],
        ),
        Route("/auth/plex/start", endpoint=dashboard["auth_plex_start"]),
        Route("/auth/plex/callback", endpoint=dashboard["auth_plex_callback"]),
        Route("/auth/link/plex", endpoint=dashboard["auth_link_plex"]),
        Route("/auth/link/plex/start", endpoint=dashboard["auth_link_plex_start"]),
        Route(
            "/auth/link/plex/callback", endpoint=dashboard["auth_link_plex_callback"]
        ),
        Route(
            "/auth/logout", endpoint=dashboard["auth_logout"], methods=["GET", "POST"]
        ),
        Mount("/static", app=StaticFiles(directory=str(_STATIC_DIR)), name="static"),
        mcp_route,
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(APIKeyMiddleware, api_key=settings.api_key)
    return app


async def health_check(request: Request) -> JSONResponse:
    """Return a simple liveness response."""
    return JSONResponse({"status": "ok", "service": "arr-mcp"})


def main() -> None:
    """Entry point: load config, configure logging, and start uvicorn."""
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)


if __name__ == "__main__":
    main()

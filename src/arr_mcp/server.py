"""arr-mcp: MCP server for home media stack management."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.tools.containers import register_container_tools
from arr_mcp.tools.conversion import register_conversion_tools
from arr_mcp.tools.filesystem import register_filesystem_tools
from arr_mcp.tools.logs import register_log_tools
from arr_mcp.tools.stacks import register_stack_tools

load_dotenv()

log = logging.getLogger(__name__)


def build_mcp_server(settings: Settings, client: ContainerClient) -> FastMCP:
    """Build and configure the FastMCP server with all tool registrations."""
    # Disable DNS rebinding protection — we use API key auth instead and the
    # server is accessed from external hosts (not just localhost).
    server = FastMCP(
        "arr-mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_container_tools(server, client)
    register_stack_tools(server, client, settings)
    register_filesystem_tools(server, settings)
    register_log_tools(server, settings)
    register_conversion_tools(server, settings)
    return server


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[len("Bearer ") :] != self.api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def create_app(settings: Settings) -> Starlette:
    """Build the Starlette ASGI app with auth middleware and MCP route."""
    client = ContainerClient(settings)
    mcp_server = build_mcp_server(settings, client)

    # Initialise the session manager and extract the /mcp route handler.
    # We then run session_manager.run() in our own lifespan so the task group
    # is always initialised before requests arrive, regardless of whether the
    # host (uvicorn or httpx test transport) calls sub-app lifespans.
    fastmcp_app = mcp_server.streamable_http_app()
    mcp_route = fastmcp_app.routes[0]  # Route("/mcp", endpoint=StreamableHTTPASGIApp)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        log.info("arr-mcp starting — runtime=%s port=%d", settings.container_runtime, settings.port)
        async with mcp_server.session_manager.run():
            yield
        log.info("arr-mcp stopped")

    routes = [
        Route("/health", endpoint=health_check),
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

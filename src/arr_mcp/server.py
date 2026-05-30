"""arr-mcp: MCP server for home media stack management."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from arr_mcp.config import Settings
from arr_mcp.runtime.client import ContainerClient
from arr_mcp.tools.containers import register_container_tools
from arr_mcp.tools.filesystem import register_filesystem_tools
from arr_mcp.tools.logs import register_log_tools
from arr_mcp.tools.stacks import register_stack_tools

load_dotenv()

log = logging.getLogger(__name__)


def build_mcp_server(settings: Settings, client: ContainerClient) -> FastMCP:
    server = FastMCP("arr-mcp")
    register_container_tools(server, client)
    register_stack_tools(server, client, settings)
    register_filesystem_tools(server, settings)
    register_log_tools(server, settings)
    return server


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[len("Bearer "):] != self.api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def create_app(settings: Settings) -> Starlette:
    client = ContainerClient(settings)
    mcp_server = build_mcp_server(settings, client)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        log.info("arr-mcp starting — runtime=%s port=%d", settings.container_runtime, settings.port)
        yield
        log.info("arr-mcp stopped")

    routes = [
        Mount("/mcp", app=mcp_server.streamable_http_app()),
        Route("/health", endpoint=health_check),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(APIKeyMiddleware, api_key=settings.api_key)
    return app


async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "arr-mcp"})


def main() -> None:
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

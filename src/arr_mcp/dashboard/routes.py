"""Dashboard route handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from arr_mcp.config import Settings
from arr_mcp.dashboard.data import get_status
from arr_mcp.runtime.client import ContainerClient

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


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
    return env


def _check_auth(request: Request, settings: Settings) -> bool:
    """Return True if the request is authorised to view the dashboard."""
    if settings.dashboard_public:
        return True
    key = request.query_params.get("key", "")
    return key == settings.api_key


def _open_claude_url(status: dict[str, Any], settings: Settings, request: Request) -> str:
    """Build the 'Open in Claude' link URL."""
    host = settings.public_url or str(request.base_url).rstrip("/")
    containers = status.get("containers", [])
    disk = status.get("disk", [])

    running = sum(1 for c in containers if c["status"] == "running")
    total = len(containers)
    disk_summary = ""
    if disk:
        d = disk[0]
        disk_summary = f", {d['used_gb']} GB of {d['total_gb']} GB used"

    prompt = (
        f"I'm managing my home media server with arr-mcp at {host}. "
        f"Current status: {running}/{total} containers running{disk_summary}."
    )
    return f"https://claude.ai/new?q={quote(prompt)}"


def make_dashboard_routes(client: ContainerClient, settings: Settings) -> dict[str, Any]:
    """Return the two dashboard route handlers as a dict."""
    jinja = _get_jinja_env()

    async def handle_dashboard(request: Request) -> Response:
        """Serve the HTML dashboard."""
        if not _check_auth(request, settings):
            return HTMLResponse("<h1>401 Unauthorized</h1>", status_code=401)
        try:
            status = await get_status(client, settings)
        except Exception as exc:
            log.exception("Error building dashboard status")
            return HTMLResponse(f"<h1>Error</h1><pre>{exc}</pre>", status_code=500)

        claude_url = _open_claude_url(status, settings, request)
        template = jinja.get_template("index.html")
        html = template.render(status=status, claude_url=claude_url, settings=settings)
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

    return {
        "dashboard": handle_dashboard,
        "api_status": handle_api_status,
    }

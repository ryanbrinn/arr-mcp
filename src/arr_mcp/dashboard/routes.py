"""Dashboard route handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from arr_mcp.config import Settings
from arr_mcp.dashboard.data import get_status
from arr_mcp.runtime.client import ContainerClient

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
    key = request.query_params.get("key", "")
    return key == settings.api_key


def make_dashboard_routes(
    client: ContainerClient, settings: Settings
) -> dict[str, Any]:
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

    return {
        "dashboard": handle_dashboard,
        "api_status": handle_api_status,
    }

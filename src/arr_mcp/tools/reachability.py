"""Service API reachability and inter-service connectivity checks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.services.base import ServiceNotConfiguredError
from arr_mcp.services.registry import ServiceRegistry
from arr_mcp.tools.services import KNOWN_SERVICES, read_download_clients

log = logging.getLogger(__name__)

_REACHABILITY_TIMEOUT = 3.0


@dataclass
class ReachabilityResult:
    """Reachability result for a single service or download client."""

    name: str
    base_url: str
    reachable: bool
    status_code: int | None = None
    error: str | None = None
    auth_ok: bool | None = None  # None = not checked


@dataclass
class DownloadClientReachability:
    """Reachability result for a download client configured in sonarr/radarr."""

    arr_service: str
    client_name: str
    implementation: str
    base_url: str
    reachable: bool
    status_code: int | None = None
    error: str | None = None


async def _check_url(
    url: str, api_key: str = "", timeout: float = _REACHABILITY_TIMEOUT
) -> tuple[bool, int | None, str | None]:
    """Perform a lightweight GET; return (reachable, status_code, error)."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=timeout)
            return resp.is_success, resp.status_code, None
    except httpx.TimeoutException:
        return False, None, f"Timeout after {timeout}s"
    except httpx.ConnectError as exc:
        return False, None, f"Connection refused: {exc}"
    except httpx.RequestError as exc:
        return False, None, str(exc)


def _extract_download_client_url(implementation: str, settings: dict) -> str | None:  # type: ignore[type-arg]
    """Derive a base URL from download client settings.

    Handles Sabnzbd, NzbGet, qBittorrent, and generic URL-based clients.
    """
    host = settings.get("host", "")
    port = settings.get("port", "")
    use_ssl = settings.get("useSsl", False)
    url_base = settings.get("urlBase", "").strip("/")

    if not host or not port:
        return None

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"
    if url_base:
        base = f"{base}/{url_base}"
    return base


def register_reachability_tools(server: FastMCP, settings: Settings) -> None:
    """Register service reachability check tools with the MCP server."""
    registry = ServiceRegistry(settings.services_dir)

    @server.tool()
    async def service_api_reachability() -> list[TextContent]:
        """Check which configured services have a reachable HTTP API.

        For each service with credentials configured, attempts a lightweight
        health-check call (2-3s timeout). Reports reachable/unreachable and
        whether the API key is valid (for arr services that return 401 on bad key).

        Only checks services that have credentials set up via credential_set
        or the corresponding env var.
        """
        available = registry.available()
        if not available:
            return [
                TextContent(
                    type="text",
                    text=(
                        "No service credentials configured. "
                        "Use credential_set to add credentials."
                    ),
                )
            ]

        results: list[ReachabilityResult] = []

        for name in available:
            try:
                client = registry.get_client(name)
            except ServiceNotConfiguredError:
                continue

            health = await client.health()
            auth_ok: bool | None = None
            if health.status_code == 401:
                auth_ok = False
            elif health.ok:
                auth_ok = True

            results.append(
                ReachabilityResult(
                    name=name,
                    base_url=client._base_url,
                    reachable=health.ok,
                    status_code=health.status_code,
                    error=health.error,
                    auth_ok=auth_ok,
                )
            )

        summary = {
            "reachable": sum(1 for r in results if r.reachable),
            "unreachable": sum(1 for r in results if not r.reachable),
            "total": len(results),
        }
        payload = {
            "summary": summary,
            "services": [
                {
                    "name": r.name,
                    "base_url": r.base_url,
                    "reachable": r.reachable,
                    "status_code": r.status_code,
                    "error": r.error,
                    "auth_ok": r.auth_ok,
                }
                for r in results
            ],
        }
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    @server.tool()
    async def inter_service_reachability() -> list[TextContent]:
        """Verify that sonarr/radarr can reach their configured download clients.

        Reads download client configuration from each arr service's database,
        then attempts a lightweight HTTP check to each configured download client.
        Reports reachable/unreachable and any connection errors.

        Only checks services whose database exists in services_dir.
        """
        services_root = Path(settings.services_dir)
        results: list[dict] = []  # type: ignore[type-arg]

        arr_services = [
            name
            for name, info in KNOWN_SERVICES.items()
            if info.db_file and info.config_format == "xml"
        ]

        for svc_name in arr_services:
            svc_dir = services_root / svc_name
            info = KNOWN_SERVICES[svc_name]
            if not info.db_file:
                continue
            db_path = svc_dir / info.db_file
            if not db_path.exists():
                continue

            clients = read_download_clients(db_path)
            if not clients:
                continue

            for dc in clients:
                if not dc.enable:
                    continue

                url = _extract_download_client_url(dc.implementation, dc.settings)
                if url is None:
                    results.append(
                        {
                            "arr_service": svc_name,
                            "client_name": dc.name,
                            "implementation": dc.implementation,
                            "base_url": None,
                            "reachable": False,
                            "error": "Could not derive URL from settings",
                        }
                    )
                    continue

                # Use api_key from settings if present
                api_key = str(dc.settings.get("apiKey", ""))
                reachable, status_code, error = await _check_url(url, api_key=api_key)
                results.append(
                    {
                        "arr_service": svc_name,
                        "client_name": dc.name,
                        "implementation": dc.implementation,
                        "base_url": url,
                        "reachable": reachable,
                        "status_code": status_code,
                        "error": error,
                    }
                )

        if not results:
            return [
                TextContent(
                    type="text",
                    text="No download client configurations found in any arr service database.",
                )
            ]

        summary = {
            "reachable": sum(1 for r in results if r["reachable"]),
            "unreachable": sum(1 for r in results if not r["reachable"]),
            "total": len(results),
        }
        payload = {"summary": summary, "download_clients": results}
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

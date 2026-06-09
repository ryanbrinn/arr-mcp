"""MCP tool for upgrade recommendations."""

from __future__ import annotations

import json
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.tasks.versions import VersionStore


def register_version_tools(server: FastMCP, settings: Settings) -> None:
    """Register version-check tools with the MCP server."""
    store = VersionStore(settings.services_dir)

    @server.tool()
    async def upgrades_available() -> list[TextContent]:
        """Return a list of services with newer versions available.

        Reads from a cache updated daily by the VersionChecker background task.
        Returns an empty list when all services are current or the cache is
        empty (no poll has run yet).
        """
        recommendations = store.get_recommendations()
        if not recommendations:
            return [TextContent(type="text", text="All services are up to date.")]

        result = {
            "upgrade_count": len(recommendations),
            "upgrades": [asdict(r) for r in recommendations],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

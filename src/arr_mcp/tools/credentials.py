"""MCP tools for managing service API credentials."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.services.credentials import CredentialStore, ServiceCredential


def register_credential_tools(server: FastMCP, settings: Settings) -> None:
    """Register credential management tools with the MCP server."""
    store = CredentialStore(settings.services_dir)

    @server.tool()
    async def credential_set(
        service: str,
        api_key: str,
        base_url: str = "",
    ) -> list[TextContent]:
        """Store or update an API credential for a service.

        Args:
            service: Service name (e.g. sonarr, radarr, plex).
            api_key: API key or token for the service.
            base_url: Optional base URL override (e.g. http://sonarr:8989).
        """
        cred = ServiceCredential(
            api_key=api_key,
            base_url=base_url or None,
        )
        store.set(service, cred)
        return [TextContent(type="text", text=f"Credential stored for {service}.")]

    @server.tool()
    async def credential_list() -> list[TextContent]:
        """List services that have credentials configured.

        Never returns key values — only service names.
        """
        configured = store.list_configured()
        if not configured:
            return [TextContent(type="text", text="No credentials configured.")]
        result = {"configured_services": configured}
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def credential_delete(service: str) -> list[TextContent]:
        """Remove the stored credential for a service.

        Args:
            service: Service name to remove credential for.
        """
        store.delete(service)
        return [TextContent(type="text", text=f"Stored credential removed for {service}.")]

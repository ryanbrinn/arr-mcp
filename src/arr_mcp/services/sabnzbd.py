"""SabnzbdClient — HTTP client for SABnzbd's query-param authenticated API."""

from __future__ import annotations

from arr_mcp.services.base import ApiResult, BaseServiceClient


class SabnzbdClient(BaseServiceClient):
    """HTTP client for SABnzbd.

    SABnzbd authenticates via an ``apikey`` query parameter rather than the
    ``X-Api-Key`` header used by *arr apps.  All GET requests inject the key
    automatically so callers don't need to pass it explicitly.
    """

    async def health(self) -> ApiResult:
        """Ping SABnzbd's version endpoint to verify the service is reachable."""
        return await self.get("/api", mode="version", output="json")

    async def get(self, path: str, **params: str) -> ApiResult:
        """GET with ``apikey`` injected into query params."""
        params.setdefault("apikey", self._api_key)
        params.setdefault("output", "json")
        return await self._request("GET", path, params=params or None)

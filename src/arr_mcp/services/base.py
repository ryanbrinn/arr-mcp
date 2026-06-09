"""BaseServiceClient — shared HTTP client foundation for all service integrations."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0


@dataclass
class ApiResult:
    """Structured result from a service API call."""

    ok: bool
    status_code: int | None = None
    data: dict | list | None = None  # type: ignore[type-arg]
    error: str | None = None


class ServiceNotConfiguredError(Exception):
    """Raised when a service client cannot be built because credentials are absent."""


class BaseServiceClient:
    """Injectable async HTTP client for a single service.

    Never raises on HTTP errors — returns an ApiResult with ok=False instead.
    Pass a custom ``http`` instance (e.g. one backed by httpx.MockTransport)
    to make the client fully unit-testable without a live service.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http
        # Subclasses can override the header name used to send the API key
        self._auth_header = "X-Api-Key"

    # ------------------------------------------------------------------
    # HTTP primitives
    # ------------------------------------------------------------------

    async def get(self, path: str, **params: str) -> ApiResult:
        """Send a GET request; return a structured result."""
        return await self._request("GET", path, params=params or None)

    async def post(self, path: str, body: dict) -> ApiResult:  # type: ignore[type-arg]
        """Send a POST request with a JSON body; return a structured result."""
        return await self._request("POST", path, json=body)

    async def delete(self, path: str) -> ApiResult:
        """Send a DELETE request; return a structured result."""
        return await self._request("DELETE", path)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health(self) -> ApiResult:
        """Ping the service to verify it is reachable and responding."""
        return await self.get(self._health_path())

    def _health_path(self) -> str:
        """Override in subclasses to point at a service-specific health endpoint."""
        return "/api/v3/system/status"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,  # type: ignore[type-arg]
        json: dict | None = None,  # type: ignore[type-arg]
    ) -> ApiResult:
        url = self._base_url + path
        headers = {self._auth_header: self._api_key, "Accept": "application/json"}

        async def _send(client: httpx.AsyncClient) -> ApiResult:
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=_DEFAULT_TIMEOUT,
                )
            except httpx.TimeoutException:
                return ApiResult(
                    ok=False, error=f"Timeout connecting to {self._base_url}"
                )
            except httpx.ConnectError as exc:
                return ApiResult(ok=False, error=f"Connection refused: {exc}")
            except httpx.RequestError as exc:
                return ApiResult(ok=False, error=str(exc))

            if not resp.is_success:
                return ApiResult(
                    ok=False,
                    status_code=resp.status_code,
                    error=f"HTTP {resp.status_code}",
                )

            try:
                data = resp.json()
            except Exception:
                data = {"text": resp.text}

            return ApiResult(ok=True, status_code=resp.status_code, data=data)

        if self._http is not None:
            return await _send(self._http)

        async with httpx.AsyncClient() as client:
            return await _send(client)

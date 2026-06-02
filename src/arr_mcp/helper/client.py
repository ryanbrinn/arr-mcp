"""Async client for communicating with the arr-helper Unix socket agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_UNAVAILABLE_MSG = (
    "Stack management requires the arr-helper agent running on the host. "
    "See docs/setup.md for installation instructions."
)


@dataclass
class HelperResponse:
    """Response from the arr-helper agent."""

    ok: bool
    output: str
    exit_code: int


class HelperClient:
    """Thin async client over the arr-helper Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._transport = httpx.AsyncHTTPTransport(uds=socket_path)
        self._client = httpx.AsyncClient(
            transport=self._transport,
            base_url="http://localhost",
            timeout=120.0,
        )

    async def call(self, op: str, **args: str) -> HelperResponse:
        """Send a command to the helper and return the response.

        Raises HelperUnavailableError if the socket cannot be reached.
        """
        payload = {"op": op, "args": args}
        try:
            r = await self._client.post("/command", json=payload)
            data = r.json()
            return HelperResponse(
                ok=data.get("ok", False),
                output=data.get("output", data.get("error", "")),
                exit_code=data.get("exit_code", 1),
            )
        except httpx.ConnectError as exc:
            raise HelperUnavailableError(self._socket_path) from exc

    async def is_available(self) -> bool:
        """Return True if the helper socket exists and responds."""
        if not Path(self._socket_path).exists():
            return False
        try:
            # quadlet_list is side-effect free — use it as a health probe
            await self.call("quadlet_list")
            return True
        except (HelperUnavailableError, Exception):
            return False

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


class HelperUnavailableError(Exception):
    """Raised when the helper socket is unreachable."""

    def __init__(self, socket_path: str) -> None:
        super().__init__(f"arr-helper socket not reachable: {socket_path}")
        self.socket_path = socket_path


def unavailable_message() -> str:
    """Return the standard message shown when the helper is not running."""
    return _UNAVAILABLE_MSG

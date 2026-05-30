"""Thin async wrapper around the container runtime socket (Docker-compatible API)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from arr_mcp.config import Settings
from arr_mcp.runtime.detector import detect_runtime

log = logging.getLogger(__name__)


class ContainerClient:
    """Async HTTP client talking to the Podman/Docker socket."""

    def __init__(self, settings: Settings) -> None:
        runtime, socket_path = detect_runtime(
            preference=settings.container_runtime,
            socket_path=settings.socket_path,
        )
        self.runtime = runtime
        self.socket_path = socket_path
        log.info("Container runtime: %s  socket: %s", runtime, socket_path)
        uds_path = socket_path.removeprefix("unix://")
        self._transport = httpx.AsyncHTTPTransport(uds_socket=uds_path)
        self._client = httpx.AsyncClient(
            transport=self._transport,
            base_url="http://localhost",
            timeout=30.0,
        )

    async def get(self, path: str, **kwargs: Any) -> Any:
        r = await self._client.get(path, **kwargs)
        r.raise_for_status()
        return r.json()

    async def post(self, path: str, **kwargs: Any) -> Any:
        r = await self._client.post(path, **kwargs)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {}

    async def delete(self, path: str, **kwargs: Any) -> Any:
        r = await self._client.delete(path, **kwargs)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {}

    async def aclose(self) -> None:
        await self._client.aclose()

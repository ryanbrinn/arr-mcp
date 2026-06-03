"""Fake Docker v1.41 API — custom httpx transport for e2e tests.

Serves just enough of the Docker REST API for all arr-mcp container tools
to exercise without a real daemon.  State is mutable so tests can seed
containers and assert side-effects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


def _encode_log_frame(text: str, stream: int = 1) -> bytes:
    """Encode a single multiplex-stream frame (8-byte header + payload)."""
    payload = text.encode()
    header = bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    return header + payload


@dataclass
class FakeContainer:
    name: str
    status: str = "running"
    image: str = "test-image"
    ports: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=lambda: ["container log line\n"])

    def to_list_item(self, cid: str) -> dict[str, Any]:
        return {
            "Id": cid,
            "Names": [f"/{self.name}"],
            "Image": self.image,
            "Status": "Up 1 hour" if self.status == "running" else self.status,
            "Ports": self.ports,
            "State": self.status,
        }

    def to_stats(self, cid: str) -> dict[str, Any]:
        return {
            "id": cid,
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000},
                "system_cpu_usage": 200_000_000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000},
                "system_cpu_usage": 100_000_000,
            },
            "memory_stats": {
                "usage": 512 * 1024 * 1024,
                "limit": 8 * 1024 * 1024 * 1024,
            },
            "networks": {
                "eth0": {"rx_bytes": 1024 * 10, "tx_bytes": 1024 * 5},
            },
        }


class FakeDockerTransport(httpx.AsyncBaseTransport):
    """Route fake Docker API requests to in-process handlers.

    Tests may mutate ``containers`` directly to seed state.
    ``calls`` records every (method, path) pair for assertions.
    """

    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {
            "plex": FakeContainer(
                "plex",
                ports=[{"PublicPort": 32400, "PrivatePort": 32400, "Type": "tcp"}],
            ),
            "sonarr": FakeContainer("sonarr", status="stopped"),
        }
        self.calls: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    # httpx transport entry point
    # ------------------------------------------------------------------

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path
        params = dict(request.url.params)

        self.calls.append((method, path))

        # /v1.41/containers/json
        if method == "GET" and path.endswith("/containers/json"):
            include_all = params.get("all", "false").lower() == "true"
            items = [
                c.to_list_item(cid)
                for cid, c in enumerate(self.containers.values())
                for cid in [str(id(c))]
                if include_all or c.status == "running"
            ]
            return self._json(items)

        # /v1.41/containers/{name}/start|stop|restart
        for action in ("start", "stop", "restart"):
            if method == "POST" and path.endswith(f"/{action}"):
                name = self._extract_name(path, action)
                if name not in self.containers:
                    return self._json({"message": f"No such container: {name}"}, 404)
                if action == "start":
                    self.containers[name].status = "running"
                elif action == "stop":
                    self.containers[name].status = "stopped"
                elif action == "restart":
                    self.containers[name].status = "running"
                return httpx.Response(204)

        # /v1.41/containers/{name} (DELETE)
        if method == "DELETE" and "/containers/" in path:
            name = path.split("/containers/")[-1].split("?")[0]
            if name not in self.containers:
                return self._json({"message": f"No such container: {name}"}, 404)
            del self.containers[name]
            return httpx.Response(204)

        # /v1.41/containers/{name}/logs
        if method == "GET" and path.endswith("/logs"):
            name = self._extract_name(path, "logs")
            container = self.containers.get(name)
            if container is None:
                return self._json({"message": f"No such container: {name}"}, 404)
            body = b"".join(_encode_log_frame(line) for line in container.logs)
            return httpx.Response(200, content=body)

        # /v1.41/containers/{cid}/stats
        if method == "GET" and path.endswith("/stats"):
            # Look up by id (we use id(container) as cid)
            for c in self.containers.values():
                if path.split("/containers/")[-1].split("/")[0] == str(id(c)):
                    return self._json(c.to_stats(str(id(c))))
            return self._json({"message": "No such container"}, 404)

        return self._json({"message": f"Not implemented: {method} {path}"}, 501)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _json(data: Any, status: int = 200) -> httpx.Response:
        return httpx.Response(
            status,
            content=json.dumps(data).encode(),
            headers={"content-type": "application/json"},
        )

    @staticmethod
    def _extract_name(path: str, suffix: str) -> str:
        """Extract container name from /v1.41/containers/{name}/{suffix}."""
        return path.split("/containers/")[-1].removesuffix(f"/{suffix}")

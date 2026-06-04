"""Container lifecycle tools."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.runtime.client import ContainerClient

log = logging.getLogger(__name__)

API = "/v1.41"


def _decode_log_stream(raw: bytes) -> str:
    """Decode a Docker/Podman multiplexed log stream into plain text.

    Each frame has an 8-byte header: 1 byte stream type, 3 bytes padding,
    4 bytes big-endian payload length.  Plain-text responses (some Podman
    versions omit framing) are returned as-is when the header parse yields
    nothing.
    """
    lines_out: list[str] = []
    i = 0
    while i < len(raw):
        if i + 8 > len(raw):
            break
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        chunk = raw[i + 8 : i + 8 + size].decode("utf-8", errors="replace")
        lines_out.append(chunk)
        i += 8 + size
    if not lines_out and raw:
        return raw.decode("utf-8", errors="replace")
    return "".join(lines_out)


def register_container_tools(server: FastMCP, client: ContainerClient) -> None:
    """Register all container lifecycle tools with the MCP server."""

    @server.tool()
    async def container_list() -> list[TextContent]:
        """List all containers with status, uptime, and ports."""
        data: list[dict[str, Any]] = await client.get(f"{API}/containers/json?all=true")
        rows = []
        for c in data:
            name = (c.get("Names") or ["?"])[0].lstrip("/")
            status = c.get("Status", "unknown")
            ports = (
                ", ".join(
                    f"{p.get('PublicPort', '?')}->{p.get('PrivatePort', '?')}/{p.get('Type', '')}"
                    for p in (c.get("Ports") or [])
                    if p.get("PublicPort")
                )
                or "none"
            )
            rows.append(f"{name:20s}  {status:30s}  ports: {ports}")
        return [TextContent(type="text", text="\n".join(rows) or "No containers found.")]

    @server.tool()
    async def container_start(name: str) -> list[TextContent]:
        """Start a stopped container by name."""
        await client.post(f"{API}/containers/{name}/start")
        return [TextContent(type="text", text=f"Started: {name}")]

    @server.tool()
    async def container_stop(name: str) -> list[TextContent]:
        """Stop a running container by name."""
        await client.post(f"{API}/containers/{name}/stop")
        return [TextContent(type="text", text=f"Stopped: {name}")]

    @server.tool()
    async def container_restart(name: str) -> list[TextContent]:
        """Restart a container by name."""
        await client.post(f"{API}/containers/{name}/restart")
        return [TextContent(type="text", text=f"Restarted: {name}")]

    @server.tool()
    async def container_remove(name: str, confirm: bool = False) -> list[TextContent]:
        """Remove a container. Requires confirm=True."""
        if not confirm:
            return [TextContent(type="text", text="Pass confirm=True to remove the container.")]
        await client.delete(f"{API}/containers/{name}?force=true")
        return [TextContent(type="text", text=f"Removed: {name}")]

    @server.tool()
    async def container_logs(name: str, lines: int = 100) -> list[TextContent]:
        """Fetch the last N log lines from a container."""
        uds = client.socket_path.removeprefix("unix://")
        transport = httpx.AsyncHTTPTransport(uds=uds)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
            r = await c.get(f"{API}/containers/{name}/logs?stdout=true&stderr=true&tail={lines}")
        if r.status_code != 200:
            msg = r.text.strip() or f"HTTP {r.status_code}"
            # Podman with journald log driver returns 500 and "configured logging driver
            # does not support reading" — surface that clearly rather than empty output.
            return [TextContent(type="text", text=f"(logs unavailable: {msg})")]
        text = _decode_log_stream(r.content)
        return [TextContent(type="text", text=text or "(no logs)")]

    @server.tool()
    async def container_stats() -> list[TextContent]:
        """Show CPU, memory, and network stats for all running containers."""
        containers: list[dict[str, Any]] = await client.get(f"{API}/containers/json")
        rows = ["NAME                 CPU%    MEM USAGE / LIMIT     NET I/O"]
        for c in containers:
            name = (c.get("Names") or ["?"])[0].lstrip("/")
            cid = c["Id"]
            try:
                s = await client.get(f"{API}/containers/{cid}/stats?stream=false")
                cpu_delta = (
                    s["cpu_stats"]["cpu_usage"]["total_usage"]
                    - s["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                sys_delta = (
                    s["cpu_stats"]["system_cpu_usage"] - s["precpu_stats"]["system_cpu_usage"]
                )
                ncpu = s["cpu_stats"].get("online_cpus", 1)
                cpu_pct = (cpu_delta / sys_delta) * ncpu * 100.0 if sys_delta > 0 else 0.0
                mem = s["memory_stats"]
                used = mem.get("usage", 0) / 1024 / 1024
                limit = mem.get("limit", 0) / 1024 / 1024
                nets = s.get("networks", {})
                rx = sum(v.get("rx_bytes", 0) for v in nets.values()) / 1024
                tx = sum(v.get("tx_bytes", 0) for v in nets.values()) / 1024
                rows.append(
                    f"{name:20s} {cpu_pct:6.2f}%  "
                    f"{used:6.1f}MB / {limit:6.1f}MB  "
                    f"{rx:.1f}kB / {tx:.1f}kB"
                )
            except Exception as exc:
                rows.append(f"{name:20s} (stats unavailable: {exc})")
        return [TextContent(type="text", text="\n".join(rows))]

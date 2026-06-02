# Architecture

## Deployment model

arr-mcp runs as a container alongside the media stack. It communicates with the container runtime via a bind-mounted Unix socket and exposes an MCP endpoint over HTTP with Bearer token authentication.

```
Claude (MCP client)
      │  HTTP + Bearer auth
      ▼
 arr-mcp container
      │  Unix socket
      ▼
 Podman/Docker runtime
      │
      ▼
 Media stack containers (plex, sonarr, radarr, ...)
```

## Target environment

- **OS**: Debian/Ubuntu
- **Runtime**: Rootless Podman under a dedicated service account (e.g. `media`)
- **Socket**: `/run/user/<UID>/podman/podman.sock` — where `<UID>` is the service account UID (`id media`)
- **Stacks**: `/opt/stacks/<stack-name>/compose.yaml`
- **Media**: `/media-server/`

## Core components

| File | Responsibility |
|---|---|
| `src/arr_mcp/server.py` | Starlette ASGI app, API key auth middleware, entry point |
| `src/arr_mcp/config.py` | Pydantic settings loaded from environment / `.env` |
| `src/arr_mcp/runtime/detector.py` | Auto-detects Podman or Docker socket at startup |
| `src/arr_mcp/runtime/client.py` | Async HTTP client over the container runtime socket |
| `src/arr_mcp/tools/containers.py` | Container lifecycle tools |
| `src/arr_mcp/tools/stacks.py` | Stack management tools |
| `src/arr_mcp/tools/filesystem.py` | Filesystem tools scoped to allowed paths |
| `src/arr_mcp/tools/logs.py` | Log reading and searching tools |
| `src/arr_mcp/tools/utils.py` | Shared utilities (ownership checks, etc.) |

## Planned: host-side helper agent

The current architecture cannot run `podman-compose` or `systemctl` commands because those binaries are not available inside the container. See [ADR-0002](adr/0002-host-side-helper-agent.md) and [issue #13](https://github.com/ryanbrinn/arr-mcp/issues/13).

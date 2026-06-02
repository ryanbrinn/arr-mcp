# Architecture

## Deployment model

arr-mcp runs as a container alongside the media stack. It communicates with the container runtime via a bind-mounted Unix socket and exposes an MCP endpoint and a read-only dashboard over HTTP.

Stack and systemd management require `arr-helper`, a small host-side process that runs as the service account and communicates with arr-mcp via a bind-mounted Unix socket.

```
Claude (MCP client)          Browser
      │  HTTP + Bearer auth       │  HTTP + ?key=
      ▼                           ▼
 ┌─────────────────────────────────────────┐
 │           arr-mcp container             │
 │  /mcp   – MCP endpoint                  │
 │  /      – read-only dashboard (Jinja2)  │
 │  /api/status – JSON status              │
 └───────────────┬─────────────────────────┘
                 │  Unix socket (podman.sock / docker.sock)
                 ▼
          Container runtime
                 │
                 ▼
   Media stack containers (plex, sonarr, radarr, ...)

 arr-helper (host process, service account)
      │  Unix socket (arr-helper.sock, bind-mounted into arr-mcp)
      ├── podman-compose up/down/pull/restart
      ├── systemctl --user start/stop/restart/status/daemon-reload
      └── read/write ~/.config/containers/systemd/*.container
```

## Target environment

- **OS**: Debian/Ubuntu
- **Runtime**: Rootless Podman under a dedicated service account (e.g. `media`)
- **Socket**: `/run/user/<UID>/podman/podman.sock` — where `<UID>` is the service account UID (`id media`)
- **Stacks**: `/opt/stacks/<stack-name>/compose.yaml`
- **Media**: `/media-server/`

## Core components

### arr-mcp (container)

| File | Responsibility |
|---|---|
| `src/arr_mcp/server.py` | Starlette ASGI app, API key auth middleware, route assembly, entry point |
| `src/arr_mcp/config.py` | Pydantic settings loaded from environment / `.env` |
| `src/arr_mcp/runtime/detector.py` | Auto-detects Podman or Docker socket at startup |
| `src/arr_mcp/runtime/client.py` | Async HTTP client over the container runtime socket |
| `src/arr_mcp/tools/containers.py` | Container lifecycle tools |
| `src/arr_mcp/tools/stacks.py` | Stack management tools (delegates to arr-helper) |
| `src/arr_mcp/tools/filesystem.py` | Filesystem tools scoped to allowed paths |
| `src/arr_mcp/tools/logs.py` | Log reading and searching tools |
| `src/arr_mcp/tools/conversion.py` | Compose ↔ Quadlet conversion tools |
| `src/arr_mcp/tools/utils.py` | Shared utilities (ownership checks, etc.) |
| `src/arr_mcp/helper/client.py` | HTTP/JSON client for the arr-helper Unix socket |
| `src/arr_mcp/dashboard/routes.py` | Dashboard route handlers |
| `src/arr_mcp/dashboard/data.py` | Status data assembly from runtime client |
| `src/arr_mcp/dashboard/templates/` | Jinja2 HTML templates |
| `src/arr_mcp/dashboard/static/` | CSS stylesheet (no external CDN) |

### arr-helper (host process)

| File | Responsibility |
|---|---|
| `src/arr_helper/server.py` | Unix socket HTTP server (hand-rolled, no framework) |
| `src/arr_helper/handlers.py` | Operation dispatch table (14 operations) |
| `src/arr_helper/validation.py` | Input validators — regex-gated, no path traversal possible |
| `src/arr_helper/subprocess.py` | Safe subprocess runner (`create_subprocess_exec`, never `shell=True`) |

## Security boundaries

| Boundary | Mechanism |
|---|---|
| MCP endpoint auth | `Authorization: Bearer <key>` header required on `/mcp` |
| Dashboard auth | `?key=<key>` query param, or `DASHBOARD_PUBLIC=true` for LAN |
| Filesystem scope | `_check_path()` restricts to `stacks_dir`, `media_dir`, `/var/log` |
| Ownership check | `is_owned_by_current_user()` blocks operations on root-owned files |
| Helper input | Regex validation on all args; `create_subprocess_exec` prevents injection |
| Helper socket | Mode `0600`, owned by service account — no other process can connect |

See [Security](security.md) and [ADR-0001](adr/0001-filesystem-ownership-scoping.md) for full details.

## Key architectural decisions

| Decision | ADR |
|---|---|
| Filesystem ownership scoping | [ADR-0001](adr/0001-filesystem-ownership-scoping.md) |
| Host-side helper agent | [ADR-0002](adr/0002-host-side-helper-agent.md) |
| Read-only dashboard (Option C) | [ADR-0003](adr/0003-frontend-strategy.md) |
| Supported runtime configurations | [ADR-0004](adr/0004-supported-runtime-configurations.md) |

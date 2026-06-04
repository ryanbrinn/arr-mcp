# Configuration

All settings are loaded from environment variables or a `.env` file in the working directory. Every variable is prefixed with `ARR_MCP_`.

## arr-mcp settings

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token for MCP endpoint auth — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_SERVICES_DIR` | `/media-server` | Root directory where your arr services live (configs, logs, data) — read-only |
| `ARR_MCP_MEDIA_DIR` | `/media-server/library` | Root directory of your media library |
| `ARR_MCP_COMPOSE_DIR` | `` | Root directory for Docker Compose projects — required for `docker-compose` runtime |
| `ARR_MCP_QUADLETS_DIR` | `~/.config/containers/systemd` | Podman quadlet unit files directory — only used for `podman` runtime |
| `ARR_MCP_CONTAINER_RUNTIME` | `docker-compose` | `docker-compose` / `docker` / `podman` / `auto` |
| `ARR_MCP_SOCKET_PATH` | `` | Explicit socket path — required when running inside a container |
| `ARR_MCP_HELPER_SOCKET` | `/run/arr-helper/arr-helper.sock` | Path to the arr-helper Unix socket |
| `ARR_MCP_DASHBOARD_PUBLIC` | `false` | Serve dashboard without auth (set `true` for LAN-only deployments) |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

## Runtime modes

The `ARR_MCP_CONTAINER_RUNTIME` setting controls which tools and dashboard sections are available:

| Runtime | Stack tools | Dashboard stacks | Use case |
|---|---|---|---|
| `docker-compose` | ✅ | ✅ | Docker with Compose files (default) |
| `docker` | ❌ | ❌ | Docker Engine, container management only |
| `podman` | ❌ | ❌ | Rootless Podman via arr-agent |

Stack tools (`stack_up`, `stack_down`, `stack_list`, etc.) and the dashboard stacks view are only available when running Docker Compose.

## Directory paths

arr-mcp works with up to four directory roots depending on your runtime:

| Purpose | Variable | Runtime | What lives here |
|---|---|---|---|
| arr service data | `ARR_MCP_SERVICES_DIR` | all | Sonarr, Radarr, SABnzbd configs, logs, databases |
| Media library | `ARR_MCP_MEDIA_DIR` | all | Your actual media files |
| Compose projects | `ARR_MCP_COMPOSE_DIR` | `docker-compose` only | Docker Compose project directories |
| Quadlet units | `ARR_MCP_QUADLETS_DIR` | `podman` only | Systemd quadlet unit files |

These can share a common root (e.g. all under `/media-server`) or live on separate mounts — configure each independently.

**`ARR_MCP_SERVICES_DIR` is read-only.** arr-mcp will never write to your service directories. Additionally, `config.xml` and database files (`*.db`, `*.db-shm`, `*.db-wal`) are blocked from read access to protect credentials and prevent database corruption.

## arr-helper settings

arr-helper reads a single environment variable:

| Variable | Default | Description |
|---|---|---|
| `HELPER_SOCKET` | `/run/arr-helper/arr-helper.sock` | Path where arr-helper creates its Unix socket |

The socket path must match `ARR_MCP_HELPER_SOCKET` on the arr-mcp side.

---

## Socket path

When running arr-mcp inside a container, `ARR_MCP_SOCKET_PATH` must be set to the bind-mounted socket path:

```bash
-e ARR_MCP_SOCKET_PATH=unix:///run/user/1000/podman/podman.sock
```

If omitted, arr-mcp will attempt to auto-detect the socket at startup, which will fail inside a container.

## Helper socket

arr-helper's socket is bind-mounted into the arr-mcp container. The default paths assume systemd's `RuntimeDirectory=arr-helper` places the socket at `/run/user/<UID>/arr-helper/arr-helper.sock` on the host.

In the arr-mcp container (quadlet or compose):

```yaml
volumes:
  - /run/user/1000/arr-helper/arr-helper.sock:/run/arr-helper/arr-helper.sock:z
```

Override the in-container path if needed:

```bash
-e ARR_MCP_HELPER_SOCKET=/run/arr-helper/arr-helper.sock
```

## Dashboard

The dashboard is served at `GET /` and requires authentication by default. Two auth modes:

**Key in query param** (default):

```
http://your-server:8081/?key=your-secret-key
```

**Public mode** (no auth, suitable for LAN-only deployments):

```bash
-e ARR_MCP_DASHBOARD_PUBLIC=true
```


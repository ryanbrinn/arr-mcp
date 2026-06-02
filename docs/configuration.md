# Configuration

All settings are loaded from environment variables or a `.env` file in the working directory. Every variable is prefixed with `ARR_MCP_`.

## arr-mcp settings

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token for MCP endpoint auth — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_STACKS_DIR` | `/opt/stacks` | Root directory for compose stacks |
| `ARR_MCP_MEDIA_DIR` | `/media-server` | Media storage root |
| `ARR_MCP_CONTAINER_RUNTIME` | `auto` | `auto` / `podman` / `docker` |
| `ARR_MCP_SOCKET_PATH` | `` | Explicit socket path — required when running inside a container |
| `ARR_MCP_HELPER_SOCKET` | `/run/arr-helper/arr-helper.sock` | Path to the arr-helper Unix socket |
| `ARR_MCP_DASHBOARD_PUBLIC` | `false` | Serve dashboard without auth (set `true` for LAN-only deployments) |
| `ARR_MCP_PUBLIC_URL` | `` | Public URL shown in the "Open in Claude" dashboard button |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

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

**"Open in Claude" button:**

Set `ARR_MCP_PUBLIC_URL` to the address Claude should reference in its context prompt:

```bash
-e ARR_MCP_PUBLIC_URL=http://mediaserver.local:8081
```

If unset, arr-mcp uses the request's `Host` header.

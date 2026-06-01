# Configuration

All settings are loaded from environment variables or a `.env` file in the working directory.

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_STACKS_DIR` | `/opt/stacks` | podman-compose stack root |
| `ARR_MCP_MEDIA_DIR` | `/media-server` | Media storage root |
| `ARR_MCP_CONTAINER_RUNTIME` | `auto` | `auto` / `podman` / `docker` |
| `ARR_MCP_SOCKET_PATH` | `` | Explicit socket path — required when running inside a container |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

## Socket path

When running arr-mcp inside a container, `ARR_MCP_SOCKET_PATH` must be set to the bind-mounted socket path:

```bash
-e ARR_MCP_SOCKET_PATH=unix:///run/user/1000/podman/podman.sock
```

If omitted, arr-mcp will attempt to auto-detect the socket at startup, which will fail inside a container.

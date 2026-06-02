# arr-mcp

![Beta](https://img.shields.io/badge/status-beta-orange)
![Version](https://img.shields.io/badge/version-0.1.0--beta.1-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Work in progress.** This project is in active development. APIs and configuration may change between releases.

MCP server for natural language management of a home media server stack — Plex, Sonarr, Radarr, SABnzbd, and more — via Podman or Docker.

Replaces Dockge. Connects to Claude as an MCP tool server so you can manage your stack conversationally.

---

## AI Disclosure

This project was co-authored with [Claude](https://claude.ai) (Anthropic). The architecture, code, and documentation were developed collaboratively between the project author and Claude in an interactive session. All code has been reviewed by the author and is maintained as a human-owned open source project.

---

## Features

- **Container lifecycle** — list, start, stop, restart, remove, logs, stats
- **Stack management** — `podman-compose` up/down/pull/restart for every stack in `/opt/stacks`
- **Compose files** — read, write, and dry-run validate compose files
- **Filesystem** — disk usage, directory listing, file read/write (scoped to allowed paths)
- **Logs** — tail and search any log file under `/var/log`, `/opt/stacks`, or `/media-server`
- **Runtime auto-detection** — prefers rootless Podman socket, falls back to Docker
- **Bearer token auth** — static API key via `Authorization: Bearer` header

## Quick start

### Podman

Replace `<MEDIA_UID>` with your service account UID (`id media`).

```bash
MEDIA_UID=$(id -u media)

podman run -d --name arr-mcp \
  -e ARR_MCP_API_KEY=your-secret-key \
  -e ARR_MCP_CONTAINER_RUNTIME=podman \
  -v /run/user/${MEDIA_UID}/podman/podman.sock:/run/user/${MEDIA_UID}/podman/podman.sock:z \
  -v /opt/stacks:/opt/stacks:z \
  -v /media-server:/media-server:z \
  -p 8081:8081 \
  ghcr.io/ryanbrinn/arr-mcp:latest
```

### Docker

```bash
docker run -d --name arr-mcp \
  -e ARR_MCP_API_KEY=your-secret-key \
  -e ARR_MCP_CONTAINER_RUNTIME=docker \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /opt/stacks:/opt/stacks \
  -v /media-server:/media-server \
  -p 8081:8081 \
  ghcr.io/ryanbrinn/arr-mcp:latest
```

### Docker Compose / Podman Compose

```yaml
services:
  arr-mcp:
    image: ghcr.io/ryanbrinn/arr-mcp:latest
    container_name: arr-mcp
    restart: unless-stopped
    ports:
      - "8081:8081"
    environment:
      ARR_MCP_API_KEY: your-secret-key
      ARR_MCP_CONTAINER_RUNTIME: podman  # or docker
    volumes:
      # Podman rootless socket — replace 1001 with your service account UID (run: id media)
      - /run/user/1001/podman/podman.sock:/run/user/1001/podman/podman.sock:z
      # Docker: use /var/run/docker.sock:/var/run/docker.sock instead
      - /opt/stacks:/opt/stacks:z
      - /media-server:/media-server:z
```

The server listens on `http://localhost:8081`.

### Health check

```bash
curl http://localhost:8081/health
```

### MCP endpoint

```
http://localhost:8081/mcp
Authorization: Bearer <your-key>
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_STACKS_DIR` | `/opt/stacks` | podman-compose stack root |
| `ARR_MCP_MEDIA_DIR` | `/media-server` | Media storage root |
| `ARR_MCP_CONTAINER_RUNTIME` | `auto` | `auto` / `podman` / `docker` |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

## Tools

### Container lifecycle
| Tool | Description |
|---|---|
| `container_list()` | All containers with status, uptime, ports |
| `container_start(name)` | Start a stopped container |
| `container_stop(name)` | Stop a running container |
| `container_restart(name)` | Restart a container |
| `container_remove(name, confirm=True)` | Remove a container (requires confirm) |
| `container_logs(name, lines)` | Fetch last N log lines |
| `container_stats()` | CPU, memory, network per container |

### Stack management
| Tool | Description |
|---|---|
| `stack_list()` | List all stacks in stacks dir |
| `stack_up(name)` | `podman-compose up -d` |
| `stack_down(name, confirm=True)` | `podman-compose down` (requires confirm) |
| `stack_pull(name)` | Pull latest images |
| `stack_restart(name)` | Down then up |

### Compose files
| Tool | Description |
|---|---|
| `compose_read(stack)` | Read compose.yaml |
| `compose_write(stack, content)` | Write compose.yaml |
| `compose_validate(stack)` | Dry-run validate |

### Filesystem
| Tool | Description |
|---|---|
| `disk_usage(path)` | Disk usage for a path |
| `directory_list(path)` | List directory contents |
| `file_read(path)` | Read a text file |
| `file_write(path, content)` | Write a file |

### Logs
| Tool | Description |
|---|---|
| `log_read(path, lines)` | Tail a log file |
| `log_search(path, query)` | Search a log file |

## Server environment

Designed for:
- **OS**: Debian/Ubuntu
- **Runtime**: Rootless Podman under a dedicated service account (e.g. `media`)
- **Socket**: `/run/user/<UID>/podman/podman.sock` — use `id media` to find the UID
- **Stacks**: `/opt/stacks/`
- **Media**: `/media-server/`

## License

MIT

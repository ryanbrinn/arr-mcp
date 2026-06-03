# arr-mcp

![Version](https://img.shields.io/pypi/v/arr-mcp-server?label=version)
![License](https://img.shields.io/badge/license-MIT-green)
![CI](https://github.com/ryanbrinn/arr-mcp/actions/workflows/ci.yaml/badge.svg)

MCP server for natural language management of a home media server stack — Plex, Sonarr, Radarr, SABnzbd, and more — via Podman or Docker.

Talk to your media server through Claude instead of SSH. Ask it to restart a stuck container, check disk usage, pull the latest images for a stack, or migrate a compose file to Podman quadlets. A read-only status dashboard is also included for household members who don't need Claude.

---

## AI Disclosure

This project was co-authored with [Claude](https://claude.ai) (Anthropic). The architecture, code, and documentation were developed collaboratively. All code has been reviewed by the author and is maintained as a human-owned open source project.

---

## Quick start

The easiest way to install on a Podman (rootless) server — run this as your service account:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/ryanbrinn/arr-mcp/main/scripts/install.sh)
```

This installs `arr-helper` on the host, generates a quadlet for `arr-mcp`, and starts both services. It asks five questions (media directory, API key, etc.) and takes about a minute.

**Requirements:** rootless Podman, `uv`, active systemd user session (`sudo loginctl enable-linger $(whoami)`).

For Docker or manual setup, see the [Getting Started guide](https://ryanbrinn.github.io/arr-mcp/getting-started/).

---

## What it does

### Talk to your server through Claude

Connect arr-mcp to Claude as an MCP server and manage your stack conversationally:

```
"Restart the radarr container"
"How much disk space is left on /media-server?"
"Pull the latest images for my media stack and bring it back up"
"Convert my compose.yaml to quadlet files"
```

### Status dashboard

A read-only dashboard is served at `http://your-server:8081/` — no Claude required. Shows container status, disk usage, and stack health with auto-refresh every 30 seconds. Useful for household members who just want to see if things are running.

---

## Features

| Category | Tools |
|---|---|
| **Containers** | list, start, stop, restart, remove, logs, stats |
| **Stacks** | up, down, pull, restart, validate (via arr-helper) |
| **Compose files** | read, write, validate |
| **Conversion** | compose → quadlets, quadlets → compose |
| **Filesystem** | disk usage, directory list, file read, write, delete |
| **Logs** | tail and search any log file |

All filesystem operations are ownership-scoped — arr-mcp cannot touch files owned by root or other users. See [Security](https://ryanbrinn.github.io/arr-mcp/security/).

---

## Architecture

```
Claude / Browser
      │
      ▼
 arr-mcp (container)          ← MCP tools + dashboard
      │  Podman socket
      ▼
 Container runtime             ← your media stack

 arr-helper (host process)    ← podman-compose, systemctl, quadlets
      │  Unix socket (bind-mounted into arr-mcp)
      ▼
 arr-mcp container
```

`arr-helper` is a small host-side process that gives arr-mcp access to `podman-compose`, `systemctl --user`, and quadlet files — things that aren't available from inside a container. The install script sets it up automatically.

---

## Connecting to Claude

### Claude.ai

Go to **Settings → Integrations** and add a remote MCP server:

```
URL:    http://your-server-ip:8081/mcp
Header: Authorization: Bearer your-api-key
```

### Claude Desktop

Claude Desktop requires a local bridge. Install [mcpproxy](https://github.com/sparfenyuk/mcp-proxy) on your local machine, then add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arr-mcp": {
      "command": "/usr/local/bin/mcpproxy",
      "args": [
        "--transport", "streamablehttp",
        "-H", "Authorization", "Bearer your-api-key",
        "http://your-server-ip:8081/mcp"
      ]
    }
  }
}
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ARR_MCP_API_KEY` | `changeme` | Bearer token — **change this** |
| `ARR_MCP_PORT` | `8081` | HTTP listen port |
| `ARR_MCP_STACKS_DIR` | `/opt/stacks` | Compose stack root |
| `ARR_MCP_MEDIA_DIR` | `/media-server` | Media storage root |
| `ARR_MCP_CONTAINER_RUNTIME` | `auto` | `auto` / `podman` / `docker` |
| `ARR_MCP_SOCKET_PATH` | `` | Explicit runtime socket path (required in containers) |
| `ARR_MCP_HELPER_SOCKET` | `/run/arr-helper/arr-helper.sock` | arr-helper socket path |
| `ARR_MCP_DASHBOARD_PUBLIC` | `false` | Skip dashboard auth (for LAN-only deployments) |
| `ARR_MCP_PUBLIC_URL` | `` | Public URL shown in the "Open in Claude" button |
| `ARR_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

Full reference: [docs/configuration](https://ryanbrinn.github.io/arr-mcp/configuration/).

---

## Supported runtimes

| Configuration | Supported |
|---|---|
| Docker Engine | ✅ |
| Docker with Docker Compose | ✅ |
| Podman (rootless) with Quadlets | ✅ |
| Podman (rooted) | ❌ |

---

## Documentation

- [Getting Started](https://ryanbrinn.github.io/arr-mcp/getting-started/)
- [Tools Reference](https://ryanbrinn.github.io/arr-mcp/tools/)
- [Configuration](https://ryanbrinn.github.io/arr-mcp/configuration/)
- [Security](https://ryanbrinn.github.io/arr-mcp/security/)
- [Architecture](https://ryanbrinn.github.io/arr-mcp/architecture/)
- [Roadmap](https://ryanbrinn.github.io/arr-mcp/roadmap/)

---

## Contributing

```bash
git clone https://github.com/ryanbrinn/arr-mcp
cd arr-mcp
uv sync --extra dev
uv run pytest
```

See [CLAUDE.md](CLAUDE.md) for development guidelines.

---

## License

MIT

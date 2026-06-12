# Getting Started

## One-command install (Podman + quadlets)

The fastest way to get started on a rootless Podman server:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/ryanbrinn/arr-mcp/main/scripts/install.sh)
```

The script asks five questions, installs `arr-helper` on the host, generates a quadlet for `arr-mcp`, and starts both services. Takes about a minute.

**Requirements:** rootless Podman, `uv`, active systemd user session.

```bash
# If you don't have uv:
curl -sSL https://astral.sh/uv/install.sh | sh

# If you haven't enabled linger for your service account:
sudo loginctl enable-linger $(whoami)
```

For Docker, or if you prefer to set things up manually, see the sections below.

---

## Requirements

- A supported container runtime — see [ADR-0004](adr/0004-supported-runtime-configurations.md) for the full list
- Claude with MCP support (Claude.ai or Claude Desktop)

## Supported configurations

**Operating system:** Linux only. Windows and macOS are not supported. The server relies on Unix domain sockets, rootless Podman with systemd quadlets, and `arr-helper` using POSIX APIs that do not exist on those platforms. WSL2 on Windows is not tested and not recommended.

| Configuration | Supported |
|---|---|
| Docker Engine | ✅ |
| Docker with Docker Compose | ✅ |
| Podman (rootless) with Quadlets | ✅ |
| Podman with podman-compose | ❌ |
| Podman (rooted) | ❌ |

---

## Docker Engine

### Setting up the service account

arr-mcp is designed to run under a dedicated unprivileged service account. Create one if you haven't already:

```bash
sudo useradd -m -s /bin/bash media
```

### Running arr-mcp

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

---

## Docker with Docker Compose

Add arr-mcp as a service in your existing `compose.yaml`:

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
      ARR_MCP_CONTAINER_RUNTIME: docker
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks
      - /media-server:/media-server
```

---

## Podman (rootless) with Quadlets

### Setting up the service account

```bash
sudo useradd -m -s /bin/bash media
sudo loginctl enable-linger media
```

Find the account's UID — you'll need it for the socket path:

```bash
id media
# uid=1001(media) gid=1001(media) ...
```

### Running arr-mcp

Replace `<MEDIA_UID>` with the UID from `id media`:

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

### Running arr-mcp as a quadlet

To have arr-mcp itself managed by systemd, create `~/.config/containers/systemd/arr-mcp.container`:

```ini
[Unit]
Description=arr-mcp MCP server
After=network-online.target
Wants=network-online.target

[Container]
Image=ghcr.io/ryanbrinn/arr-mcp:latest
ContainerName=arr-mcp
Environment=ARR_MCP_API_KEY=your-secret-key
Environment=ARR_MCP_CONTAINER_RUNTIME=podman
Volume=/run/user/%U/podman/podman.sock:/run/user/%U/podman/podman.sock:z
Volume=/opt/stacks:/opt/stacks:z
Volume=/media-server:/media-server:z
PublishPort=8081:8081

[Service]
Restart=on-failure

[Install]
WantedBy=default.target
```

Then reload and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now arr-mcp
```

---

## arr-helper

`arr-helper` is a small host-side process that gives arr-mcp access to `podman-compose`, `systemctl --user`, and quadlet files — none of which are available from inside a container. Without it, stack management tools return a message explaining what's missing; all other tools continue to work.

!!! tip
    The [one-command installer](#one-command-install-podman-quadlets) handles arr-helper setup automatically. The steps below are for manual installs only.

### Installing

`arr-helper` ships as part of the `arr-mcp` package. On the host machine (as the service account):

```bash
uv tool install arr-mcp
```

### Running as a systemd user service

Create `~/.config/systemd/user/arr-helper.service`:

```ini
[Unit]
Description=arr-mcp host-side helper agent
After=network.target

[Service]
ExecStart=%h/.local/bin/arr-helper
Restart=on-failure
RuntimeDirectory=arr-helper
RuntimeDirectoryMode=0700

[Install]
WantedBy=default.target
```

Enable and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now arr-helper
```

The socket will be created at `/run/user/<UID>/arr-helper/arr-helper.sock`.

### Mounting the socket into arr-mcp

Add the socket volume to your arr-mcp run command:

**Docker / podman-compose:**

```yaml
volumes:
  - /run/user/1000/arr-helper/arr-helper.sock:/run/arr-helper/arr-helper.sock:z
```

**Quadlet:**

```ini
Volume=/run/user/%U/arr-helper/arr-helper.sock:/run/arr-helper/arr-helper.sock:z
```

Replace `1000` / `%U` with the service account UID.

### Verifying

```bash
# Check the helper is running
systemctl --user status arr-helper

# Ask arr-mcp if it can reach the helper (via Claude or curl)
curl -H "Authorization: Bearer your-key" http://localhost:8081/api/status
```

If `stack_list` returns stack names rather than the "arr-helper required" message, the helper is connected.

---

## Health check

```bash
curl http://localhost:8081/health
```

## Dashboard

The read-only status dashboard is served at `GET /`. Open it in a browser:

```
http://your-server-ip:8081/?key=your-secret-key
```

It shows container status, disk usage, and stack health, and auto-refreshes every 30 seconds.

On first run, you'll be redirected to a setup page to create the first
(admin) account — either a local username/password or by signing in with
Plex. See [Configuration](configuration.md#dashboard) for the full auth
options.

## Connecting to Claude

### A note on SSH access

arr-mcp's guardrails restrict what the AI can read and return through the MCP tools — service config files containing API keys, for example, are explicitly blocked. These restrictions only apply to the MCP channel.

If the AI agent you connect to arr-mcp also has SSH credentials (or any other shell access) to the same server, it can read those files directly and the MCP guardrails provide no protection. This is not a flaw in arr-mcp — it is an inherent property of how access channels compose.

**Recommendation:** treat SSH and MCP as separate channels with different trust levels.

- Give the AI MCP access to arr-mcp for media stack operations.
- Keep SSH credentials for yourself. Do not provide them to the same AI session unless you have a specific reason and understand that doing so removes the credential-protection guarantees.

For more detail on what the guardrails do and do not cover, see [Security — Guardrail scope](security.md#guardrail-scope).

### Claude.ai (web)

Claude.ai supports remote MCP servers natively. Go to **Settings → Integrations** and add:

```
http://your-server-ip:8081/mcp
```

With header:
```
Authorization: Bearer your-secret-key
```

### Claude Desktop

Claude Desktop only supports local stdio-based MCP servers and cannot connect to remote HTTP servers directly. You need **mcpproxy** installed on your local machine to bridge the connection.

1. Download mcpproxy from [github.com/sparfenyuk/mcp-proxy](https://github.com/sparfenyuk/mcp-proxy)
2. Add the following to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arr-mcp": {
      "command": "<path-to-mcpproxy>",
      "args": [
        "--transport",
        "streamablehttp",
        "-H",
        "Authorization",
        "Bearer your-secret-key",
        "http://your-server-ip:8081/mcp"
      ]
    }
  }
}
```

Replace `<path-to-mcpproxy>` with the full path to the mcpproxy executable on your local machine:

- **Windows**: `C:\Users\username\bin\mcpproxy.exe`
- **macOS/Linux**: `/usr/local/bin/mcpproxy`

!!! note
    mcpproxy runs on the machine running Claude Desktop — not on the media server.

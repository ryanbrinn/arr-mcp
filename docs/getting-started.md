# Getting Started

## Requirements

- A supported container runtime — see [ADR-0004](adr/0004-supported-runtime-configurations.md) for the full list
- Claude with MCP support (Claude.ai or Claude Desktop)

## Supported configurations

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

## Health check

```bash
curl http://localhost:8081/health
```

## Connecting to Claude

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

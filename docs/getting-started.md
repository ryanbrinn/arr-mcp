# Getting Started

## Requirements

- Rootless Podman or Docker, running under a dedicated service account
- Claude with MCP support (Claude.ai or Claude Desktop)

## Setting up the service account

arr-mcp is designed to run under a dedicated unprivileged service account (e.g. `media`). Create one if you haven't already:

```bash
sudo useradd -m -s /bin/bash media
sudo loginctl enable-linger media
```

Find the account's UID — you'll need it for the socket path:

```bash
id media
# uid=1001(media) gid=1001(media) ...
```

## Running the server

### Podman

Replace `<MEDIA_UID>` with the UID of your service account (from `id media` above).

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

## Health check

```bash
curl http://localhost:8081/health
```

## Connecting to Claude

Add the following to your Claude MCP configuration:

```json
{
  "mcpServers": {
    "arr-mcp": {
      "url": "http://localhost:8081/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-key"
      }
    }
  }
}
```
